"""Servidor FastAPI do J.A.R.V.I.S. — Backend, Auth por PIN, Gemini Multimodal e Function Calling."""

from __future__ import annotations

import logging
import mimetypes
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import UploadFile as StarletteUploadFile

import database
import tools

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("jarvis")

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_TOOL_ROUNDS = 8

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/gif",
    "image/heic",
    "image/heif",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
}


DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"

ALLOWED_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-4-hydrogen",
    "gemini-3.5-flash-lite",
    "gemini-4-argon",
)


def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if key in ("", "sua_chave_gemini_aqui", "your_api_key_here"):
        return ""
    return key


def get_gemini_model() -> str:
    return os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL


def resolve_gemini_model(requested_model: str | None = None) -> str:
    if requested_model is None or not requested_model.strip():
        return get_gemini_model()
    candidate = requested_model.strip()
    if candidate not in ALLOWED_GEMINI_MODELS:
        allowed_str = ", ".join(ALLOWED_GEMINI_MODELS)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Modelo inválido: '{candidate}'. Modelos permitidos: {allowed_str}.",
        )
    return candidate


def get_jarvis_pin() -> str:
    return os.getenv("JARVIS_PIN", "1234").strip() or "1234"


# ---------------------------------------------------------------------------
# System Instructions (Personalidade J.A.R.V.I.S.)
# ---------------------------------------------------------------------------


def build_system_instruction(voice_mode: bool) -> str:
    base = (
        "Você é J.A.R.V.I.S., um assistente pessoal executivo de altíssimo nível, "
        "operando em um tablet Android como interface HUD pessoal.\n\n"
        "PERSONALIDADE E TOM DE VOZ:\n"
        "- Responda SEMPRE em português do Brasil.\n"
        "- Adote um tom educado, analítico, direto, proativo e levemente sofisticado "
        "(estilo mordomo executivo/estrategista confiável, sem caricaturas exageradas).\n"
        "- Antecipe próximos passos úteis quando pertinente, mantendo foco e clareza.\n\n"
        "USO OBRIGATÓRIO DE MEMÓRIA E FERRAMENTAS:\n"
        "- Antes de responder a perguntas sobre rotina, resumo do dia, pendências, "
        "preferências, datas ou contexto pessoal, consulte proativamente as ferramentas "
        "`buscar_memorias`, `listar_tarefas` e `obter_data_hora`.\n"
        "- Quando o usuário compartilhar fatos duradouros, preferências, metas, nomes ou "
        "datas importantes, registre-os automaticamente com `salvar_memoria`.\n"
        "- Quando o usuário mencionar algo que precisa fazer, crie a pendência com `adicionar_tarefa`; "
        "quando informar que finalizou algo, conclua com `concluir_tarefa`.\n"
        "- Quando pedir para anotar uma ideia, ata ou resumo de documento/estudo, use `salvar_nota`.\n"
        "- Sempre confirme brevemente as ações executadas em ferramentas.\n\n"
        "ANÁLISE MULTIMODAL:\n"
        "- Ao receber PDFs, imagens, prints ou documentos, analise-os com rigor técnico: "
        "extraia pontos-chave, dados relevantes, prazos ou inconsistências e responda "
        "exatamente ao que o usuário solicitou.\n"
    )

    if voice_mode:
        base += (
            "\nMODO VOZ ATIVO (PRIORIDADE MÁXIMA):\n"
            "- Esta resposta será lida em voz alta (TTS) no tablet.\n"
            "- Seja CONCISO, natural e fluido na fala (preferencialmente 2 a 5 frases diretas).\n"
            "- EVITE listas gigantescas, tabelas extensas ou excesso de formatação Markdown.\n"
            "- Resuma o essencial em voz alta e, se houver muitos detalhes, ofereça exibir o "
            "detalhamento completo na tela.\n"
        )
    else:
        base += (
            "\nMODO TEXTO ATIVO:\n"
            "- Estruture respostas com clareza usando Markdown limpo (negrito, listas concisas, "
            "tabelas ou blocos de código quando agregarem valor real).\n"
        )

    return base


# ---------------------------------------------------------------------------
# FastAPI Lifespan & App
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    logger.info(
        "J.A.R.V.I.S. inicializado | Modelo ativo: %s | Modelos permitidos: %s | API Key configurada: %s | DB: %s",
        get_gemini_model(),
        ", ".join(ALLOWED_GEMINI_MODELS),
        bool(get_gemini_api_key()),
        database.DB_PATH,
    )
    yield


app = FastAPI(
    title="J.A.R.V.I.S. Personal AI Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Segurança por PIN (X-Jarvis-Pin)
# ---------------------------------------------------------------------------


def verify_pin(x_jarvis_pin: str | None = Header(default=None, alias="X-Jarvis-Pin")) -> str:
    expected = get_jarvis_pin()
    if not x_jarvis_pin or not secrets.compare_digest(x_jarvis_pin.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Acesso negado: PIN inválido ou cabeçalho X-Jarvis-Pin ausente.",
        )
    return x_jarvis_pin


# ---------------------------------------------------------------------------
# Modelos Pydantic
# ---------------------------------------------------------------------------


class TaskCreate(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=300)
    prazo: str | None = Field(default=None, max_length=120)
    prioridade: str = Field(default="média")


class MemoryCreate(BaseModel):
    chave: str = Field(..., min_length=1, max_length=120)
    valor: str = Field(..., min_length=1, max_length=2000)
    categoria: str = Field(default="geral", max_length=80)


class NoteCreate(BaseModel):
    titulo: str = Field(..., min_length=1, max_length=200)
    conteudo: str = Field(..., min_length=1, max_length=20000)
    tag: str = Field(default="geral", max_length=80)


class ChatJsonRequest(BaseModel):
    message: str = ""
    voice_mode: bool = False
    session_id: str = "default"
    model: str | None = None


# ---------------------------------------------------------------------------
# Motor Gemini com Function Calling + Multimodal
# ---------------------------------------------------------------------------


FALLBACK_GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-4-hydrogen",
    "gemini-4-argon",
]


def _create_gemini_client(api_key: str) -> genai.Client:
    use_vertex = os.getenv("GEMINI_USE_VERTEXAI", "").strip().lower() in ("1", "true", "yes")
    # Passa vertexai=False explicitamente para chaves AQ. funcionarem na Gemini API sem erro de Vertex AI
    return genai.Client(vertexai=use_vertex, api_key=api_key)


def _generate_with_fallback(
    client: genai.Client,
    model_name: str,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
) -> tuple[Any, str]:
    candidates = [model_name] + [m for m in FALLBACK_GEMINI_MODELS if m != model_name]
    last_exc: Exception | None = None
    for candidate in candidates:
        try:
            resp = client.models.generate_content(
                model=candidate,
                contents=contents,
                config=config,
            )
            return resp, candidate
        except Exception as exc:
            err_str = str(exc)
            if "404" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                logger.warning("Modelo %s indisponível (%s). Tentando fallback...", candidate, err_str[:120])
                last_exc = exc
                continue
            raise
    if last_exc:
        raise last_exc
    raise RuntimeError("Nenhum modelo Gemini disponível.")


def _run_gemini_turn(
    history_rows: list[dict[str, Any]],
    user_text: str,
    voice_mode: bool,
    file_bytes: bytes | None = None,
    file_mime: str | None = None,
    file_name: str | None = None,
    model_name: str | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    active_model = model_name or get_gemini_model()
    api_key = get_gemini_api_key()
    if not api_key:
        return (
            "Senhor, a variável de ambiente `GEMINI_API_KEY` ainda não está configurada no servidor. "
            "Defina sua chave do Google AI Studio no arquivo `.env` (ou nas variáveis do ambiente de deploy) "
            "e reinicie o serviço para ativar meu núcleo cognitivo.\n\n"
            "Enquanto isso, todos os painéis locais de **Tarefas**, **Memórias** e **Notas** seguem operacionais.",
            [],
            active_model,
        )

    client = _create_gemini_client(api_key)

    contents: list[types.Content] = []
    for row in history_rows:
        role = "model" if row["role"] == "assistant" else "user"
        text = row["content"]
        if row.get("attachment_name") and role == "user":
            text = f"[Anexo anterior: {row['attachment_name']}]\n{text}"
        contents.append(
            types.Content(
                role=role,
                parts=[types.Part.from_text(text=text)],
            )
        )

    current_parts: list[types.Part] = []
    if file_bytes and file_mime:
        current_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=file_mime))
        prompt_prefix = f"Arquivo anexado: {file_name or 'documento'} ({file_mime}).\n"
        current_parts.append(
            types.Part.from_text(
                text=f"{prompt_prefix}{user_text}" if user_text else f"{prompt_prefix}Analise este arquivo e destaque os pontos-chave."
            )
        )
    else:
        current_parts.append(types.Part.from_text(text=user_text))

    contents.append(types.Content(role="user", parts=current_parts))

    config = types.GenerateContentConfig(
        system_instruction=build_system_instruction(voice_mode=voice_mode),
        tools=tools.TOOL_FUNCTIONS,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        temperature=0.4 if voice_mode else 0.5,
    )

    executed_tools: list[dict[str, Any]] = []
    final_text = ""

    for _round in range(MAX_TOOL_ROUNDS):
        response, active_model = _generate_with_fallback(
            client=client,
            model_name=active_model,
            contents=contents,
            config=config,
        )

        function_calls = response.function_calls or []
        if not function_calls:
            final_text = (response.text or "").strip()
            break

        # Preserva a resposta do modelo (incluindo thought signatures / function_call parts)
        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)

        tool_response_parts: list[types.Part] = []
        for fc in function_calls:
            fn_name = fc.name
            fn_args = dict(fc.args) if fc.args else {}
            logger.info("Executando ferramenta: %s(%s)", fn_name, fn_args)
            result = tools.execute_tool(fn_name, fn_args)

            executed_tools.append(
                {
                    "name": fn_name,
                    "label": tools.TOOL_LABELS.get(fn_name, fn_name),
                    "args": fn_args,
                    "success": bool(result.get("sucesso", True)),
                }
            )
            tool_response_parts.append(
                types.Part.from_function_response(
                    name=fn_name,
                    response=result,
                )
            )

        contents.append(types.Content(role="user", parts=tool_response_parts))
    else:
        final_text = (
            "Concluí as consultas solicitadas, senhor, porém atingi o limite de encadeamento de ferramentas "
            "nesta interação. Deseja que eu detalhe algum item específico?"
        )

    if not final_text:
        final_text = "Operação concluída, senhor. Como posso prosseguir?"

    return final_text, executed_tools, active_model


# ---------------------------------------------------------------------------
# Rotas Públicas (PWA, Healthcheck e Frontend)
# ---------------------------------------------------------------------------


@app.get("/health")
@app.get("/api/health")
async def healthcheck() -> dict[str, Any]:
    return {
        "status": "online",
        "service": "jarvis",
        "model": get_gemini_model(),
        "allowed_models": list(ALLOWED_GEMINI_MODELS),
    }


@app.get("/", include_in_schema=False)
async def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/manifest.json", include_in_schema=False)
async def serve_manifest() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "manifest.json",
        media_type="application/manifest+json",
    )


@app.get("/sw.js", include_in_schema=False)
async def serve_service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Service-Worker-Allowed": "/",
        },
    )


# ---------------------------------------------------------------------------
# Rotas Protegidas da API (Exigem X-Jarvis-Pin)
# ---------------------------------------------------------------------------


@app.post("/api/auth/verify")
async def api_verify_pin(_pin: str = Depends(verify_pin)) -> dict[str, Any]:
    return {
        "authenticated": True,
        "model": get_gemini_model(),
        "allowed_models": list(ALLOWED_GEMINI_MODELS),
        "api_key_configured": bool(get_gemini_api_key()),
        "clock": tools.obter_data_hora(),
        "stats": database.get_stats(),
    }


@app.get("/api/status")
async def api_status(_pin: str = Depends(verify_pin)) -> dict[str, Any]:
    return {
        "status": "online",
        "model": get_gemini_model(),
        "allowed_models": list(ALLOWED_GEMINI_MODELS),
        "api_key_configured": bool(get_gemini_api_key()),
        "clock": tools.obter_data_hora(),
        "stats": database.get_stats(),
    }


@app.get("/api/history")
async def api_get_history(
    session_id: str = Query(default="default"),
    limit: int = Query(default=40, ge=1, le=200),
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    messages = database.get_recent_messages(session_id=session_id, limit=limit)
    return {"messages": messages}


@app.delete("/api/history")
async def api_clear_history(
    session_id: str = Query(default="default"),
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    deleted = database.clear_messages(session_id=session_id)
    return {"sucesso": True, "removidas": deleted, "stats": database.get_stats()}


@app.post("/api/chat")
async def api_chat(
    request: Request,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    content_type = (request.headers.get("content-type") or "").lower()
    message = ""
    voice_mode = False
    session_id = "default"
    requested_model: str | None = None
    file: StarletteUploadFile | None = None

    if "application/json" in content_type:
        try:
            raw_body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Corpo JSON inválido.") from exc
        if not isinstance(raw_body, dict):
            raise HTTPException(status_code=400, detail="O corpo JSON deve ser um objeto.")
        try:
            payload = ChatJsonRequest.model_validate(raw_body)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        message = payload.message
        voice_mode = payload.voice_mode
        session_id = payload.session_id.strip() or "default"
        requested_model = payload.model
    else:
        form = await request.form()
        raw_message = form.get("message")
        message = raw_message if isinstance(raw_message, str) else ""
        raw_voice = form.get("voice_mode")
        voice_mode = (
            raw_voice.strip().lower() in ("1", "true", "yes", "on")
            if isinstance(raw_voice, str)
            else False
        )
        raw_session = form.get("session_id")
        session_id = (
            raw_session.strip() or "default"
            if isinstance(raw_session, str)
            else "default"
        )
        raw_model = form.get("model")
        requested_model = raw_model if isinstance(raw_model, str) else None
        raw_file = form.get("file")
        if isinstance(raw_file, StarletteUploadFile):
            file = raw_file

    selected_model = resolve_gemini_model(requested_model)
    user_text = message.strip()
    file_bytes: bytes | None = None
    file_mime: str | None = None
    file_name: str | None = None

    if file is not None and file.filename:
        file_name = Path(file.filename).name
        file_bytes = await file.read()
        if len(file_bytes) == 0:
            raise HTTPException(status_code=400, detail="O arquivo anexado está vazio.")
        if len(file_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Arquivo excede o limite máximo de 20 MB.",
            )

        guessed_mime = (file.content_type or "").split(";")[0].strip().lower()
        if not guessed_mime or guessed_mime == "application/octet-stream":
            ext_mime, _ = mimetypes.guess_type(file_name)
            guessed_mime = (ext_mime or "").lower()

        if guessed_mime == "image/jpg":
            guessed_mime = "image/jpeg"

        if guessed_mime not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=(
                    f"Formato não suportado ({guessed_mime or 'desconhecido'}). "
                    "Envie PDF, imagem (PNG, JPG, WEBP, GIF, HEIC) ou texto."
                ),
            )
        file_mime = guessed_mime

    if not user_text and not file_bytes:
        raise HTTPException(
            status_code=400,
            detail="Envie uma mensagem de texto, comando de voz ou um arquivo anexo.",
        )

    history_before = database.get_recent_messages(session_id=session_id, limit=18)

    display_user_text = user_text or f"Analise o arquivo anexado: {file_name}"
    user_msg = database.add_message(
        role="user",
        content=display_user_text,
        session_id=session_id,
        attachment_name=file_name,
        attachment_mime=file_mime,
        voice_mode=voice_mode,
    )

    try:
        reply_text, executed_tools, used_model = await run_in_threadpool(
            _run_gemini_turn,
            history_before,
            user_text,
            voice_mode,
            file_bytes,
            file_mime,
            file_name,
            selected_model,
        )
    except Exception as exc:
        logger.exception("Erro ao consultar o Gemini")
        err_msg = str(exc)
        if "API_KEY_INVALID" in err_msg or "API key not valid" in err_msg:
            friendly = "A chave `GEMINI_API_KEY` configurada parece inválida. Verifique o valor no `.env`."
        elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
            friendly = "Limite temporário de requisições da API Gemini atingido. Aguarde alguns instantes e tente novamente."
        else:
            friendly = f"Falha na comunicação com o núcleo Gemini: {err_msg}"
        return JSONResponse(
            status_code=502,
            content={"detail": friendly},
        )

    assistant_msg = database.add_message(
        role="assistant",
        content=reply_text,
        session_id=session_id,
        voice_mode=voice_mode,
        tool_calls=executed_tools,
    )

    return {
        "reply": reply_text,
        "model": used_model,
        "user_message": user_msg,
        "assistant_message": assistant_msg,
        "tools_used": executed_tools,
        "api_key_configured": bool(get_gemini_api_key()),
        "stats": database.get_stats(),
    }


# ---------------------------------------------------------------------------
# CRUD Direto para o HUD (Tarefas, Memórias e Notas)
# ---------------------------------------------------------------------------


@app.get("/api/tasks")
async def api_list_tasks(
    status_filter: str = Query(default="todas", alias="status"),
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    return {"tasks": database.list_tasks(status=status_filter), "stats": database.get_stats()}


@app.post("/api/tasks", status_code=201)
async def api_create_task(
    payload: TaskCreate,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    task = database.add_task(
        titulo=payload.titulo,
        prazo=payload.prazo,
        prioridade=payload.prioridade,
    )
    return {"task": task, "stats": database.get_stats()}


@app.patch("/api/tasks/{task_id}/toggle")
async def api_toggle_task(
    task_id: int,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    task = database.toggle_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    return {"task": task, "stats": database.get_stats()}


@app.delete("/api/tasks/{task_id}")
async def api_delete_task(
    task_id: int,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    deleted = database.delete_task(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada.")
    return {"sucesso": True, "stats": database.get_stats()}


@app.get("/api/memories")
async def api_list_memories(
    termo: str = Query(default=""),
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    return {"memories": database.search_memories(termo=termo), "stats": database.get_stats()}


@app.post("/api/memories", status_code=201)
async def api_create_memory(
    payload: MemoryCreate,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    result = database.save_memory(
        chave=payload.chave,
        valor=payload.valor,
        categoria=payload.categoria,
    )
    return {"result": result, "stats": database.get_stats()}


@app.delete("/api/memories/{memory_id}")
async def api_delete_memory(
    memory_id: int,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    deleted = database.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memória não encontrada.")
    return {"sucesso": True, "stats": database.get_stats()}


@app.get("/api/notes")
async def api_list_notes(
    tag: str | None = Query(default=None),
    termo: str | None = Query(default=None),
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    return {"notes": database.list_notes(tag=tag, termo=termo), "stats": database.get_stats()}


@app.post("/api/notes", status_code=201)
async def api_create_note(
    payload: NoteCreate,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    note = database.save_note(
        titulo=payload.titulo,
        conteudo=payload.conteudo,
        tag=payload.tag,
    )
    return {"note": note, "stats": database.get_stats()}


@app.delete("/api/notes/{note_id}")
async def api_delete_note(
    note_id: int,
    _pin: str = Depends(verify_pin),
) -> dict[str, Any]:
    deleted = database.delete_note(note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Nota não encontrada.")
    return {"sucesso": True, "stats": database.get_stats()}


# Arquivos estáticos montados por último
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
