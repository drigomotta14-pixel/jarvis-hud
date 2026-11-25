"""Ferramentas (Function Calling) expostas ao Gemini pelo J.A.R.V.I.S."""

from __future__ import annotations

from typing import Any, Callable

import database

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
    """Cria uma nova tarefa ou pendência na lista do usuário.

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
    """Lista as tarefas do usuário filtradas por status.

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
    """Marca uma tarefa pendente como concluída usando seu ID numérico ou parte do título.

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


TOOL_FUNCTIONS: list[Callable[..., dict[str, Any]]] = [
    salvar_memoria,
    buscar_memorias,
    adicionar_tarefa,
    listar_tarefas,
    concluir_tarefa,
    salvar_nota,
    obter_data_hora,
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
