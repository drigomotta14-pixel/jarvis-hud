"""Ferramentas (Function Calling) expostas ao Gemini pelo J.A.R.V.I.S."""

from __future__ import annotations

import base64
import html
import logging
import os
import re
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any, Callable

import database
import google_services

logger = logging.getLogger("jarvis.tools")

DIAS_SEMANA_PT = {
    0: "segunda-feira",
    1: "terça-feira",
    2: "quarta-feira",
    3: "quinta-feira",
    4: "sexta-feira",
    5: "sábado",
    6: "domingo",
}

MESES_PT = {
    1: "janeiro",
    2: "fevereiro",
    3: "março",
    4: "abril",
    5: "maio",
    6: "junho",
    7: "julho",
    8: "agosto",
    9: "setembro",
    10: "outubro",
    11: "novembro",
    12: "dezembro",
}

WEB_SEARCH_FALLBACK_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-4-hydrogen",
    "gemini-4-argon",
]


def _parse_iso_brt(value: str, end_of_day: bool = False) -> datetime:
    """Converte data/hora ISO 8601 (ou YYYY-MM-DD) para datetime com fuso America/Sao_Paulo."""
    raw = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        dt = datetime.strptime(raw, "%Y-%m-%d")
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.replace(tzinfo=database.SAO_PAULO_TZ)

    normalized = raw.replace(" ", "T").replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=database.SAO_PAULO_TZ)
    return dt


def _escape_drive_query(text: str) -> str:
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _header_value(headers: list[dict[str, Any]], name: str) -> str:
    target = name.lower()
    for h in headers or []:
        if (h.get("name") or "").lower() == target:
            return str(h.get("value") or "")
    return ""


def _decode_b64url(data: str) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def _strip_html_tags(raw_html: str) -> str:
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _extract_email_body_and_attachments(payload: dict[str, Any]) -> tuple[str, list[str]]:
    """Extrai texto legível (preferindo text/plain) e lista de anexos de um payload do Gmail."""
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime = (part.get("mimeType") or "").lower()
        filename = (part.get("filename") or "").strip()
        if filename:
            attachments.append(filename)

        body = part.get("body") or {}
        data = body.get("data")
        if data:
            decoded = _decode_b64url(data)
            if mime == "text/plain":
                plain_parts.append(decoded)
            elif mime == "text/html":
                html_parts.append(decoded)

        for child in part.get("parts") or []:
            walk(child)

    walk(payload or {})

    if plain_parts:
        text = "\n".join(p.strip() for p in plain_parts if p.strip())
    elif html_parts:
        text = _strip_html_tags("\n".join(html_parts))
    else:
        text = ""

    return text.strip(), attachments


# ---------------------------------------------------------------------------
# Ferramentas Locais (Memória, Tarefas, Notas e Relógio)
# ---------------------------------------------------------------------------


def salvar_memoria(chave: str, valor: str, categoria: str = "geral") -> dict[str, Any]:
    """Salva ou atualiza permanentemente um fato, preferência, data importante ou contexto do usuário.

    Args:
        chave: Identificador curto e descritivo da memória (ex.: 'nome_usuario', 'cafe_preferido', 'aniversario_mae').
        valor: Informação detalhada a ser lembrada.
        categoria: Categoria organizacional (ex.: 'pessoal', 'preferencias', 'trabalho', 'estudos', 'datas', 'geral').
    """
    result = database.save_memory(chave=chave, valor=valor, categoria=categoria)
    return {
        "sucesso": True,
        "mensagem": f"Memória '{chave}' {result['acao']} na categoria '{result['memoria']['categoria']}'.",
        "memoria": result["memoria"],
    }


def buscar_memorias(termo: str = "") -> dict[str, Any]:
    """Pesquisa memórias persistentes salvas sobre o usuário.

    Args:
        termo: Palavra-chave para filtrar memórias por chave, valor ou categoria. Deixe vazio para listar as memórias mais recentes.
    """
    items = database.search_memories(termo=termo)
    return {
        "sucesso": True,
        "quantidade": len(items),
        "termo_buscado": termo,
        "memorias": items,
    }


def adicionar_tarefa(titulo: str, prazo: str = "", prioridade: str = "média") -> dict[str, Any]:
    """Cria uma nova tarefa ou pendência na lista local do usuário.

    Args:
        titulo: Descrição clara da tarefa a ser realizada.
        prazo: Data ou prazo opcional (ex.: '2026-11-30', 'amanhã às 18h', 'sexta-feira'). Deixe vazio se não houver prazo.
        prioridade: Nível de prioridade da tarefa: 'alta', 'média' ou 'baixa'.
    """
    task = database.add_task(titulo=titulo, prazo=prazo or None, prioridade=prioridade)
    return {
        "sucesso": True,
        "mensagem": f"Tarefa #{task['id']} adicionada com prioridade {task['prioridade']}.",
        "tarefa": task,
    }


def listar_tarefas(status: str = "pendente") -> dict[str, Any]:
    """Lista as tarefas locais do usuário filtradas por status.

    Args:
        status: Filtro de status: 'pendente', 'concluida' ou 'todas'.
    """
    tasks = database.list_tasks(status=status)
    return {
        "sucesso": True,
        "status_filtrado": status,
        "quantidade": len(tasks),
        "tarefas": tasks,
    }


def concluir_tarefa(id_ou_titulo: str) -> dict[str, Any]:
    """Marca uma tarefa local pendente como concluída usando seu ID numérico ou parte do título.

    Args:
        id_ou_titulo: ID numérico da tarefa (ex.: '3') ou título/trecho do título da tarefa.
    """
    task = database.complete_task(id_ou_titulo=id_ou_titulo)
    if not task:
        return {
            "sucesso": False,
            "mensagem": f"Não encontrei nenhuma tarefa pendente correspondente a '{id_ou_titulo}'.",
        }
    return {
        "sucesso": True,
        "mensagem": f"Tarefa #{task['id']} ('{task['titulo']}') marcada como concluída.",
        "tarefa": task,
    }


def salvar_nota(titulo: str, conteudo: str, tag: str = "geral") -> dict[str, Any]:
    """Salva uma anotação rápida, resumo de estudo, ata ou ideia no caderno persistente.

    Args:
        titulo: Título conciso da nota.
        conteudo: Conteúdo completo da anotação (pode usar Markdown).
        tag: Tag de classificação (ex.: 'estudos', 'trabalho', 'ideias', 'resumo', 'geral').
    """
    note = database.save_note(titulo=titulo, conteudo=conteudo, tag=tag)
    return {
        "sucesso": True,
        "mensagem": f"Nota '{note['titulo']}' salva com a tag #{note['tag']}.",
        "nota": note,
    }


def obter_data_hora() -> dict[str, Any]:
    """Retorna a data, hora, dia da semana e fuso horário atuais em Brasília (America/Sao_Paulo)."""
    agora = database.now_brt()
    dia_semana = DIAS_SEMANA_PT[agora.weekday()]
    mes = MESES_PT[agora.month]
    return {
        "sucesso": True,
        "fuso_horario": "America/Sao_Paulo",
        "iso": agora.isoformat(timespec="seconds"),
        "data": agora.strftime("%d/%m/%Y"),
        "hora": agora.strftime("%H:%M:%S"),
        "dia_semana": dia_semana,
        "extenso": f"{dia_semana}, {agora.day} de {mes} de {agora.year}, às {agora.strftime('%H:%M')}",
    }


# ---------------------------------------------------------------------------
# Ferramentas Google Workspace (Agenda, Gmail, Drive e Google Tarefas)
# ---------------------------------------------------------------------------


def listar_eventos_agenda(
    data_inicio: str = "",
    data_fim: str = "",
    max_resultados: int = 15,
    busca: str = "",
) -> dict[str, Any]:
    """Lista os próximos eventos da Google Agenda do usuário.

    Args:
        data_inicio: Data/hora inicial em ISO 8601 ou 'YYYY-MM-DD' (ex.: '2026-11-25'). Se vazio, usa agora.
        data_fim: Data/hora final em ISO 8601 ou 'YYYY-MM-DD'. Se vazio, busca os próximos 7 dias a partir de data_inicio.
        max_resultados: Quantidade máxima de eventos a retornar (padrão 15, máximo 50).
        busca: Texto opcional para filtrar eventos por título, descrição ou local.
    """
    try:
        service = google_services.build_google_service("calendar", "v3")
    except google_services.GoogleAuthRequiredError as exc:
        return {"sucesso": False, "autenticacao_necessaria": True, "mensagem": str(exc)}

    inicio_dt = _parse_iso_brt(data_inicio) if data_inicio.strip() else database.now_brt()
    fim_dt = (
        _parse_iso_brt(data_fim, end_of_day=True)
        if data_fim.strip()
        else inicio_dt + timedelta(days=7)
    )
    limite = max(1, min(int(max_resultados or 15), 50))

    params: dict[str, Any] = {
        "calendarId": "primary",
        "timeMin": inicio_dt.isoformat(),
        "timeMax": fim_dt.isoformat(),
        "maxResults": limite,
        "singleEvents": True,
        "orderBy": "startTime",
    }
    if busca.strip():
        params["q"] = busca.strip()

    resp = service.events().list(**params).execute()
    eventos = []
    for item in resp.get("items", []):
        start = item.get("start") or {}
        end = item.get("end") or {}
        eventos.append(
            {
                "id": item.get("id"),
                "titulo": item.get("summary") or "(Sem título)",
                "inicio": start.get("dateTime") or start.get("date"),
                "fim": end.get("dateTime") or end.get("date"),
                "local": item.get("location") or "",
                "descricao": (item.get("description") or "")[:400],
                "participantes": [a.get("email") for a in item.get("attendees", []) if a.get("email")],
                "link": item.get("htmlLink") or "",
            }
        )

    return {
        "sucesso": True,
        "periodo": {"inicio": inicio_dt.isoformat(), "fim": fim_dt.isoformat()},
        "quantidade": len(eventos),
        "eventos": eventos,
    }


def criar_evento_agenda(
    titulo: str,
    inicio: str,
    fim: str = "",
    descricao: str = "",
    local: str = "",
    participantes: str = "",
) -> dict[str, Any]:
    """Cria um novo evento na Google Agenda principal do usuário.

    Args:
        titulo: Título do compromisso ou reunião.
        inicio: Data/hora de início em ISO 8601 (ex.: '2026-11-26T15:00:00') ou 'YYYY-MM-DD' para dia inteiro.
        fim: Data/hora de término em ISO 8601 ou 'YYYY-MM-DD'. Se vazio, define duração padrão de 1 hora (ou 1 dia se dia inteiro).
        descricao: Descrição ou pauta opcional do evento.
        local: Local físico ou link de reunião opcional.
        participantes: E-mails dos convidados separados por vírgula (opcional).
    """
    try:
        service = google_services.build_google_service("calendar", "v3")
    except google_services.GoogleAuthRequiredError as exc:
        return {"sucesso": False, "autenticacao_necessaria": True, "mensagem": str(exc)}

    inicio_raw = inicio.strip()
    is_all_day = bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", inicio_raw))

    if is_all_day:
        start_date = datetime.strptime(inicio_raw, "%Y-%m-%d").date()
        if fim.strip() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fim.strip()):
            end_date = datetime.strptime(fim.strip(), "%Y-%m-%d").date()
            if end_date <= start_date:
                end_date = start_date + timedelta(days=1)
        else:
            end_date = start_date + timedelta(days=1)
        body: dict[str, Any] = {
            "summary": titulo.strip(),
            "start": {"date": start_date.isoformat()},
            "end": {"date": end_date.isoformat()},
        }
    else:
        start_dt = _parse_iso_brt(inicio_raw)
        end_dt = _parse_iso_brt(fim) if fim.strip() else start_dt + timedelta(hours=1)
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(hours=1)
        body = {
            "summary": titulo.strip(),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "America/Sao_Paulo"},
        }

    if descricao.strip():
        body["description"] = descricao.strip()
    if local.strip():
        body["location"] = local.strip()
    if participantes.strip():
        emails = [e.strip() for e in participantes.split(",") if e.strip()]
        if emails:
            body["attendees"] = [{"email": e} for e in emails]

    created = service.events().insert(calendarId="primary", body=body).execute()
    start_val = (created.get("start") or {}).get("dateTime") or (created.get("start") or {}).get("date")
    end_val = (created.get("end") or {}).get("dateTime") or (created.get("end") or {}).get("date")

    return {
        "sucesso": True,
        "mensagem": f"Evento '{created.get('summary')}' criado na Google Agenda.",
        "evento": {
            "id": created.get("id"),
            "titulo": created.get("summary"),
            "inicio": start_val,
            "fim": end_val,
            "local": created.get("location") or "",
            "link": created.get("htmlLink") or "",
        },
    }


def buscar_emails(consulta: str = "", max_resultados: int = 10) -> dict[str, Any]:
    """Busca e-mails no Gmail do usuário usando filtros ou palavras-chave.

    Args:
        consulta: Consulta no formato de busca do Gmail (ex.: 'is:unread', 'from:chefe@empresa.com', 'fatura'). Deixe vazio para listar os mais recentes.
        max_resultados: Quantidade máxima de e-mails a retornar (padrão 10, máximo 25).
    """
    try:
        service = google_services.build_google_service("gmail", "v1")
    except google_services.GoogleAuthRequiredError as exc:
        return {"sucesso": False, "autenticacao_necessaria": True, "mensagem": str(exc)}

    limite = max(1, min(int(max_resultados or 10), 25))
    list_params: dict[str, Any] = {"userId": "me", "maxResults": limite}
    if consulta.strip():
        list_params["q"] = consulta.strip()

    resp = service.users().messages().list(**list_params).execute()
    msg_refs = resp.get("messages") or []

    emails = []
    for ref in msg_refs:
        meta = (
            service.users()
            .messages()
            .get(
                userId="me",
                id=ref["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            )
            .execute()
        )
        headers = (meta.get("payload") or {}).get("headers") or []
        label_ids = meta.get("labelIds") or []
        emails.append(
            {
                "id": meta.get("id"),
                "thread_id": meta.get("threadId"),
                "de": _header_value(headers, "From"),
                "para": _header_value(headers, "To"),
                "assunto": _header_value(headers, "Subject") or "(Sem assunto)",
                "data": _header_value(headers, "Date"),
                "trecho": meta.get("snippet") or "",
                "nao_lido": "UNREAD" in label_ids,
            }
        )

    return {
        "sucesso": True,
        "consulta": consulta,
        "quantidade": len(emails),
        "emails": emails,
    }


def ler_email(email_id: str) -> dict[str, Any]:
    """Lê o conteúdo completo de um e-mail específico do Gmail pelo seu ID.

    Args:
        email_id: ID do e-mail obtido por meio da ferramenta buscar_emails.
    """
    try:
        service = google_services.build_google_service("gmail", "v1")
    except google_services.GoogleAuthRequiredError as exc:
        return {"sucesso": False, "autenticacao_necessaria": True, "mensagem": str(exc)}

    msg = service.users().messages().get(userId="me", id=email_id.strip(), format="full").execute()
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    body_text, attachments = _extract_email_body_and_attachments(payload)

    if len(body_text) > 12000:
        body_text = body_text[:12000] + "\n...[conteúdo truncado]"

    return {
        "sucesso": True,
        "email": {
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "de": _header_value(headers, "From"),
            "para": _header_value(headers, "To"),
            "cc": _header_value(headers, "Cc"),
            "assunto": _header_value(headers, "Subject") or "(Sem assunto)",
            "data": _header_value(headers, "Date"),
            "corpo": body_text or (msg.get("snippet") or ""),
            "anexos": attachments,
        },
    }


def criar_rascunho_email(
    destinatario: str,
    assunto: str,
    corpo: str,
    cc: str = "",
    responder_thread_id: str = "",
) -> dict[str, Any]:
    """Cria um rascunho de e-mail na pasta Rascunhos do Gmail (não envia automaticamente).

    Args:
        destinatario: Endereço de e-mail do destinatário (ou vários separados por vírgula).
        assunto: Assunto do e-mail.
        corpo: Texto completo da mensagem.
        cc: Endereços em cópia separados por vírgula (opcional).
        responder_thread_id: ID de thread do Gmail caso seja resposta a uma conversa existente (opcional).
    """
    try:
        service = google_services.build_google_service("gmail", "v1")
    except google_services.GoogleAuthRequiredError as exc:
        return {"sucesso": False, "autenticacao_necessaria": True, "mensagem": str(exc)}

    email_msg = EmailMessage()
    email_msg["To"] = destinatario.strip()
    email_msg["Subject"] = assunto.strip()
    if cc.strip():
        email_msg["Cc"] = cc.strip()
    email_msg.set_content(corpo.strip())

    raw_bytes = base64.urlsafe_b64encode(email_msg.as_bytes()).decode("ascii")
    draft_message: dict[str, Any] = {"raw": raw_bytes}
    if responder_thread_id.strip():
        draft_message["threadId"] = responder_thread_id.strip()

    draft = service.users().drafts().create(userId="me", body={"message": draft_message}).execute()
    return {
        "sucesso": True,
        "mensagem": f"Rascunho criado no Gmail para {destinatario.strip()} com assunto '{assunto.strip()}'.",
        "rascunho": {
            "id": draft.get("id"),
            "message_id": (draft.get("message") or {}).get("id"),
            "destinatario": destinatario.strip(),
            "assunto": assunto.strip(),
        },
    }


def buscar_arquivos_drive(
    consulta: str = "",
    tipo: str = "",
    max_resultados: int = 15,
) -> dict[str, Any]:
    """Busca arquivos e pastas no Google Drive do usuário (somente leitura).

    Args:
        consulta: Termo para pesquisar no nome ou conteúdo dos arquivos. Deixe vazio para listar os arquivos modificados recentemente.
        tipo: Filtro opcional de tipo: 'pdf', 'doc', 'planilha', 'apresentacao', 'pasta' ou 'imagem'.
        max_resultados: Quantidade máxima de arquivos a retornar (padrão 15, máximo 30).
    """
    try:
        service = google_services.build_google_service("drive", "v3")
    except google_services.GoogleAuthRequiredError as exc:
        return {"sucesso": False, "autenticacao_necessaria": True, "mensagem": str(exc)}

    clauses = ["trashed = false"]
    if consulta.strip():
        escaped = _escape_drive_query(consulta.strip())
        clauses.append(f"(name contains '{escaped}' or fullText contains '{escaped}')")

    tipo_map = {
        "pdf": "mimeType = 'application/pdf'",
        "doc": "mimeType = 'application/vnd.google-apps.document'",
        "documento": "mimeType = 'application/vnd.google-apps.document'",
        "planilha": "mimeType = 'application/vnd.google-apps.spreadsheet'",
        "sheet": "mimeType = 'application/vnd.google-apps.spreadsheet'",
        "apresentacao": "mimeType = 'application/vnd.google-apps.presentation'",
        "slide": "mimeType = 'application/vnd.google-apps.presentation'",
        "pasta": "mimeType = 'application/vnd.google-apps.folder'",
        "folder": "mimeType = 'application/vnd.google-apps.folder'",
        "imagem": "mimeType contains 'image/'",
    }
    tipo_key = tipo.strip().lower()
    if tipo_key in tipo_map:
        clauses.append(tipo_map[tipo_key])

    limite = max(1, min(int(max_resultados or 15), 30))
    resp = (
        service.files()
        .list(
            q=" and ".join(clauses),
            pageSize=limite,
            orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime, size, webViewLink, owners(displayName,emailAddress))",
        )
        .execute()
    )

    arquivos = []
    for f in resp.get("files") or []:
        owners = f.get("owners") or []
        owner_name = owners[0].get("displayName") or owners[0].get("emailAddress") if owners else ""
        arquivos.append(
            {
                "id": f.get("id"),
                "nome": f.get("name"),
                "mime_type": f.get("mimeType"),
                "modificado_em": f.get("modifiedTime"),
                "tamanho_bytes": int(f["size"]) if f.get("size") else None,
                "proprietario": owner_name,
                "link": f.get("webViewLink") or "",
            }
        )

    return {
        "sucesso": True,
        "consulta": consulta,
        "quantidade": len(arquivos),
        "arquivos": arquivos,
    }


def gerenciar_google_tarefas(
    acao: str = "listar",
    titulo: str = "",
    notas: str = "",
    prazo: str = "",
    tarefa_id: str = "",
    lista_id: str = "@default",
    incluir_concluidas: bool = False,
) -> dict[str, Any]:
    """Gerencia listas e tarefas do Google Tasks (listar, criar, concluir, excluir ou listar listas).

    Args:
        acao: Operação desejada: 'listar', 'criar', 'concluir', 'excluir' ou 'listas'.
        titulo: Título da tarefa (obrigatório em 'criar'; opcional para localizar em 'concluir'/'excluir').
        notas: Detalhes ou observações opcionais da tarefa ao criar.
        prazo: Data de vencimento opcional em 'YYYY-MM-DD' ou ISO 8601 ao criar.
        tarefa_id: ID da tarefa no Google Tasks (para 'concluir' ou 'excluir').
        lista_id: ID da lista de tarefas (padrão '@default').
        incluir_concluidas: Se True, inclui tarefas concluídas ao listar.
    """
    try:
        service = google_services.build_google_service("tasks", "v1")
    except google_services.GoogleAuthRequiredError as exc:
        return {"sucesso": False, "autenticacao_necessaria": True, "mensagem": str(exc)}

    op = (acao or "listar").strip().lower()
    target_list = (lista_id or "@default").strip() or "@default"

    if op in ("listas", "tasklists", "listar_listas"):
        resp = service.tasklists().list(maxResults=50).execute()
        listas = [
            {"id": item.get("id"), "titulo": item.get("title"), "atualizada_em": item.get("updated")}
            for item in resp.get("items") or []
        ]
        return {"sucesso": True, "acao": "listas", "quantidade": len(listas), "listas": listas}

    if op in ("listar", "list"):
        resp = (
            service.tasks()
            .list(
                tasklist=target_list,
                maxResults=50,
                showCompleted=bool(incluir_concluidas),
                showHidden=bool(incluir_concluidas),
            )
            .execute()
        )
        tarefas = [
            {
                "id": item.get("id"),
                "titulo": item.get("title") or "",
                "notas": item.get("notes") or "",
                "status": item.get("status"),
                "prazo": item.get("due") or "",
                "atualizada_em": item.get("updated") or "",
            }
            for item in resp.get("items") or []
        ]
        return {
            "sucesso": True,
            "acao": "listar",
            "lista_id": target_list,
            "quantidade": len(tarefas),
            "tarefas": tarefas,
        }

    if op in ("criar", "adicionar", "create", "add"):
        if not titulo.strip():
            return {"sucesso": False, "mensagem": "Informe o título da tarefa para criar no Google Tarefas."}
        body: dict[str, Any] = {"title": titulo.strip()}
        if notas.strip():
            body["notes"] = notas.strip()
        if prazo.strip():
            due_dt = _parse_iso_brt(prazo)
            body["due"] = due_dt.strftime("%Y-%m-%dT00:00:00.000Z")
        created = service.tasks().insert(tasklist=target_list, body=body).execute()
        return {
            "sucesso": True,
            "acao": "criar",
            "mensagem": f"Tarefa '{created.get('title')}' criada no Google Tarefas.",
            "tarefa": {
                "id": created.get("id"),
                "titulo": created.get("title"),
                "notas": created.get("notes") or "",
                "prazo": created.get("due") or "",
                "status": created.get("status"),
            },
        }

    # Resolve tarefa por ID ou título para concluir/excluir
    resolved_id = tarefa_id.strip()
    resolved_title = titulo.strip()
    if op in ("concluir", "completar", "complete", "done", "excluir", "remover", "deletar", "delete"):
        if not resolved_id and resolved_title:
            resp = service.tasks().list(tasklist=target_list, maxResults=100, showCompleted=False).execute()
            needle = resolved_title.lower()
            for item in resp.get("items") or []:
                item_title = (item.get("title") or "").strip()
                if item_title.lower() == needle or needle in item_title.lower():
                    resolved_id = item.get("id") or ""
                    resolved_title = item_title
                    break

        if not resolved_id:
            return {
                "sucesso": False,
                "mensagem": "Não foi possível localizar a tarefa no Google Tarefas. Informe tarefa_id ou o título exato.",
            }

        if op in ("concluir", "completar", "complete", "done"):
            updated = (
                service.tasks()
                .patch(tasklist=target_list, task=resolved_id, body={"status": "completed"})
                .execute()
            )
            return {
                "sucesso": True,
                "acao": "concluir",
                "mensagem": f"Tarefa '{updated.get('title') or resolved_title}' concluída no Google Tarefas.",
                "tarefa": {"id": updated.get("id"), "titulo": updated.get("title"), "status": updated.get("status")},
            }

        service.tasks().delete(tasklist=target_list, task=resolved_id).execute()
        return {
            "sucesso": True,
            "acao": "excluir",
            "mensagem": f"Tarefa '{resolved_title or resolved_id}' removida do Google Tarefas.",
            "tarefa_id": resolved_id,
        }

    return {
        "sucesso": False,
        "mensagem": f"Ação desconhecida '{acao}'. Use: 'listar', 'criar', 'concluir', 'excluir' ou 'listas'.",
    }


# ---------------------------------------------------------------------------
# Pesquisa Web em Tempo Real (Chamada auxiliar ao Gemini com GoogleSearch)
# ---------------------------------------------------------------------------


def pesquisar_web(consulta: str) -> dict[str, Any]:
    """Pesquisa informações atualizadas na web usando o Gemini com Google Search grounding.

    Args:
        consulta: Pergunta ou termos de pesquisa atualizados (ex.: notícias recentes, cotações, previsão do tempo, documentação).
    """
    termo = (consulta or "").strip()
    if not termo:
        return {"sucesso": False, "mensagem": "Informe uma consulta para pesquisar na web."}

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key in ("", "sua_chave_gemini_aqui", "your_api_key_here"):
        return {
            "sucesso": False,
            "mensagem": "A chave GEMINI_API_KEY não está configurada para realizar pesquisa web.",
        }

    from google import genai
    from google.genai import types

    use_vertex = os.getenv("GEMINI_USE_VERTEXAI", "").strip().lower() in ("1", "true", "yes")
    client = genai.Client(vertexai=use_vertex, api_key=api_key)

    primary_model = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    candidates = [primary_model] + [m for m in WEB_SEARCH_FALLBACK_MODELS if m != primary_model]

    config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.2,
    )
    prompt = (
        "Pesquise na web usando Google Search e responda em português do Brasil de forma objetiva, "
        f"precisa e atualizada à seguinte consulta:\n\n{termo}"
    )

    response = None
    used_model = primary_model
    last_exc: Exception | None = None

    for candidate in candidates:
        try:
            response = client.models.generate_content(
                model=candidate,
                contents=prompt,
                config=config,
            )
            used_model = candidate
            break
        except Exception as exc:
            err_str = str(exc)
            if "404" in err_str or "503" in err_str or "UNAVAILABLE" in err_str:
                logger.warning("pesquisar_web: modelo %s indisponível (%s). Tentando fallback...", candidate, err_str[:120])
                last_exc = exc
                continue
            raise

    if response is None:
        if last_exc:
            raise last_exc
        return {"sucesso": False, "mensagem": "Nenhum modelo Gemini disponível para pesquisa web."}

    fontes: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    try:
        candidates_list = getattr(response, "candidates", None) or []
        if candidates_list:
            gm = getattr(candidates_list[0], "grounding_metadata", None)
            chunks = getattr(gm, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", None) if web else None
                title = getattr(web, "title", None) if web else None
                if uri and uri not in seen_urls:
                    seen_urls.add(uri)
                    fontes.append({"titulo": title or uri, "url": uri})
    except Exception:
        pass

    return {
        "sucesso": True,
        "consulta": termo,
        "modelo": used_model,
        "resposta": (getattr(response, "text", None) or "").strip(),
        "fontes": fontes[:8],
    }


TOOL_FUNCTIONS: list[Callable[..., dict[str, Any]]] = [
    salvar_memoria,
    buscar_memorias,
    adicionar_tarefa,
    listar_tarefas,
    concluir_tarefa,
    salvar_nota,
    obter_data_hora,
    listar_eventos_agenda,
    criar_evento_agenda,
    buscar_emails,
    ler_email,
    criar_rascunho_email,
    buscar_arquivos_drive,
    gerenciar_google_tarefas,
    pesquisar_web,
]

TOOL_REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    fn.__name__: fn for fn in TOOL_FUNCTIONS
}

TOOL_LABELS: dict[str, str] = {
    "salvar_memoria": "Memória salva",
    "buscar_memorias": "Memória consultada",
    "adicionar_tarefa": "Tarefa criada",
    "listar_tarefas": "Tarefas consultadas",
    "concluir_tarefa": "Tarefa concluída",
    "salvar_nota": "Nota salva",
    "obter_data_hora": "Relógio verificado",
    "listar_eventos_agenda": "Agenda consultada",
    "criar_evento_agenda": "Evento criado",
    "buscar_emails": "E-mails buscados",
    "ler_email": "E-mail lido",
    "criar_rascunho_email": "Rascunho criado",
    "buscar_arquivos_drive": "Drive pesquisado",
    "gerenciar_google_tarefas": "Google Tarefas",
    "pesquisar_web": "Pesquisa web",
}


def execute_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Executa com segurança uma ferramenta registrada pelo nome."""
    fn = TOOL_REGISTRY.get(name)
    if fn is None:
        return {"sucesso": False, "erro": f"Ferramenta desconhecida: {name}"}
    try:
        return fn(**(args or {}))
    except TypeError as exc:
        return {"sucesso": False, "erro": f"Parâmetros inválidos para '{name}': {exc}"}
    except Exception as exc:
        return {"sucesso": False, "erro": f"Falha ao executar '{name}': {exc}"}
