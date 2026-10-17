import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from subscricao import catalogo as catalogo_
from subscricao import gerador_de_validacoes as gerador
from subscricao import identificadores as identificadores_
from subscricao.classificacao import OUTRO
from subscricao.config import MODEL_ID
from subscricao.conversao import converter
from subscricao.fraude import configuracao as fraude_
from subscricao.fraude import prompts_poc
from subscricao.fraude.forense import avaliador as forense_
from subscricao.fraude.forense import calibracao as calibracao_forense
from subscricao.fraude.forense import validacoes as validacoes_arquivo
from subscricao.pipeline import analisar_fraude_documentos, extrair_documentos, validar_documentos, verificar_identificadores_documentos
from subscricao.validacoes import VALIDACOES, carregar_validacoes
from subscricao.validacoes.ValidateDocument import descreve

EXEMPLO_FICHA_CADASTRO = Path(__file__).parent / "exemplos" / "ficha_cadastro.json"

COLUNAS_CAMPOS = ["nome", "tipo", "extracao", "descricao"]

SITUACOES = {
    "OK": "✅ válida",
    "ESPERAR_DOCUMENTOS": "⏳ aguardando documentos",
    "ERRO_INTERNO": "⚠️ erro na validação",
    "NAO_ENCONTRADO": "❌ não encontrado",
}

# Modos da tela. O analista só envia os documentos da proposta; o desenvolvedor também altera o
# catálogo e a configuração de fraude
ANALISTA, DESENVOLVEDOR = "Analista", "Desenvolvedor"

ROTULOS_RISCO = {"ALTO": "Alto", "MEDIO": "Médio", "BAIXO": "Baixo", "NULO": "Nulo"}

AJUDA_RISCO = (
    "Define a prompt do orquestrador e quais avaliadores rodam na análise de fraude (aba Fraude). "
    "Alto, médio e baixo avaliam o documento, do mais rigoroso ao mais tolerante. No risco nulo o documento "
    "nunca é classificado como suspeito: só é invalidado se o arquivo trouxer mais de um documento."
)

ROTULOS_PROMPT = {
    "orquestrador": "Orquestrador",
    "textual": "Avaliador textual",
    "visual": "Avaliador visual",
    "metadados": "Avaliador de metadados",
}

SITUACOES_DO_IDENTIFICADOR = {
    identificadores_.OK: "✅ confere",
    identificadores_.INVALIDO: "❌ com problema",
    identificadores_.NAO_VERIFICAVEL: "⚠️ não deu para conferir",
}

SITUACOES_DA_VALIDACAO_DO_ARQUIVO = {
    validacoes_arquivo.REPROVADA: "❌ reprovada",
    validacoes_arquivo.NAO_CONFERIDA: "⚠️ não conferida",
    validacoes_arquivo.APROVADA: "✅ aprovada",
    validacoes_arquivo.NAO_SE_APLICA: "— não se aplica",
}

ROTULOS_CONTAGEM = {"criticas": "críticas", "moderadas": "moderadas", "baixas": "baixas"}

STATUS_FRAUDE = {
    "AUTÊNTICO": "✅ Autêntico",
    "SUSPEITO": "🚩 Suspeito",
    "INVÁLIDO": "⛔ Inválido",
}


def texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False)
    return str(valor)


def campos_de_instrucoes(instrucoes, chave, altura=120):
    """Uma área de texto por prompt de fraude. Retorna {prompt: texto}."""
    return {
        prompt: st.text_area(rotulo, value=(instrucoes or {}).get(prompt, ""), height=altura, key=f"{chave}_{prompt}")
        for prompt, rotulo in ROTULOS_PROMPT.items()
    }


# --- proposta: ficha de cadastro, documentos, validações e fraude ---

def classificar_e_extrair(arquivos, catalogo):
    """
    Converte os arquivos enviados em markdown, classifica e extrai. Os arquivos ficam em uma
    pasta temporária enquanto a proposta estiver na tela, porque a análise de fraude os usa.
    """
    anterior = st.session_state.pop("pasta", None)
    if anterior is not None:
        anterior.cleanup()
    pasta = tempfile.TemporaryDirectory(prefix="subscricao_", ignore_cleanup_errors=True)
    st.session_state["pasta"] = pasta

    with st.status("Processando os documentos...", expanded=True) as status:
        documentos = []
        for arquivo in arquivos:
            st.write(f"Convertendo {arquivo.name} em markdown")
            path = Path(pasta.name) / arquivo.name
            path.write_bytes(arquivo.getvalue())
            documentos.append(converter(path))

        st.write(f"Classificando e extraindo com {MODEL_ID}")
        resultados = extrair_documentos(documentos, catalogo)
        status.update(label="Documentos processados", state="complete", expanded=False)

    st.session_state["resultados"] = resultados
    st.session_state["documentos"] = documentos


def linhas_validacao(validacoes):
    linhas = []
    for nome, resultado in validacoes.items():
        linhas.append({
            "validação": nome.removeprefix("validacao_"),
            "tipo": resultado["tipo"],
            "situação": SITUACOES.get(resultado["regras_subscricao_errors"], "❌ inválida"),
            "procurado": texto(resultado["trecho_procurado"]),
            "encontrado": texto(resultado["trecho_encontrado"]),
            "% match": round(resultado["percent_match"], 1),
        })
    return linhas


def mostrar_validacoes_do_arquivo(validacoes):
    """Validações do arquivo feitas por código: a situação de cada uma e, nas reprovadas, a flag que ela gera."""
    if not validacoes:
        return

    reprovadas = sum(validacao["situacao"] == validacoes_arquivo.REPROVADA for validacao in validacoes)
    conferidas = sum(validacao["situacao"] in (validacoes_arquivo.APROVADA, validacoes_arquivo.REPROVADA) for validacao in validacoes)
    st.caption(
        f"Validações do arquivo: {conferidas} conferidas, {reprovadas} reprovada(s). "
        "Uma validação aprovada não atesta autenticidade: diz só que aquela conferência não achou problema."
    )

    def flag(validacao):
        if validacao["situacao"] != validacoes_arquivo.REPROVADA:
            return ""
        return "só informa" if validacao["severidade"] == validacoes_arquivo.INFORMATIVA else validacao["severidade"].lower()

    # as reprovadas primeiro, as que não se aplicam por último
    ordem = list(SITUACOES_DA_VALIDACAO_DO_ARQUIVO)
    st.dataframe(
        [{
            "situação": SITUACOES_DA_VALIDACAO_DO_ARQUIVO[validacao["situacao"]],
            "validação": validacao["titulo"],
            "flag": flag(validacao),
            "detalhe": validacao["detalhe"],
        } for validacao in sorted(validacoes, key=lambda validacao: ordem.index(validacao["situacao"]))],
        hide_index=True,
        width="stretch",
    )


def mostrar_forense(forense):
    """Resultado do avaliador forense: nível, pontuação, formato do arquivo, validações e relatório."""
    if not forense:
        return

    st.markdown("**Análise forense do arquivo**")
    if "erro" in forense:
        st.warning(f"A análise forense falhou: {forense['erro']}")
        mostrar_validacoes_do_arquivo(forense.get("validacoes"))
        return

    coluna_nivel, coluna_score, coluna_formato = st.columns(3)
    coluna_nivel.metric("Nível de suspeição", forense["nivel"])
    coluna_score.metric("Score forense", "—" if forense["pontuacao"] is None else f"{forense['pontuacao']}/10")
    coluna_formato.metric("Formato do arquivo", ", ".join(forense["formatos"]))
    # o nível baixo é lido como "documento sem problemas": a legenda diz o que ele de fato afirma
    if forense["nivel"] == forense_.NAO_ANALISAVEL:
        st.caption("Neste formato não há o que medir no arquivo: a análise forense não diz nada sobre este documento.")
    elif forense["nivel"] == forense_.BAIXO and forense.get("alcance") == forense_.ALCANCE_LIMITADO:
        st.caption("Alcance limitado: neste formato quase nada pode ser medido. O nível baixo diz pouco sobre este documento.")
    elif forense["nivel"] == forense_.BAIXO:
        st.caption(
            "Nível baixo quer dizer que o arquivo não tem rastro de edição. Um documento refeito do zero não deixa "
            "rastro: isso aparece nos metadados, nas assinaturas e no conteúdo, não aqui."
        )
    mostrar_validacoes_do_arquivo(forense.get("validacoes"))
    with st.expander("Relatório forense"):
        st.code(forense["relatorio"], language=None, wrap_lines=True)


def mostrar_fraude(fraude):
    orquestrador = fraude["output_Evaluator"]

    st.markdown("**Análise de fraude**")
    coluna_status, coluna_score, coluna_risco = st.columns(3)
    coluna_status.metric("Situação", STATUS_FRAUDE.get(orquestrador["status_fraude"], orquestrador["status_fraude"]))
    coluna_score.metric("Fraud score", orquestrador.get("fraud_score"))
    coluna_risco.metric("Nível de risco do documento", ROTULOS_RISCO[fraude["nivel_risco"]])

    # O status sai das flags, pelas regras de decisão do nível de risco
    decisao = orquestrador.get("decisao")
    if decisao:
        contagem = ", ".join(f"{quantidade} {ROTULOS_CONTAGEM[nome]}" for nome, quantidade in decisao["contagem"].items())
        regra = f"regra atendida: {decisao['regra']}" if decisao["regra"] else "nenhuma regra de decisão atendida"
        st.caption(f"Flags: {contagem} · {regra}")

    st.write(orquestrador.get("reasoning_summary", ""))
    if orquestrador.get("flags"):
        st.dataframe(
            [{coluna: texto(flag.get(coluna)) for coluna in ("severity", "category", "source", "description", "evidence")} for flag in orquestrador["flags"]],
            hide_index=True,
            width="stretch",
        )

    mostrar_forense(fraude.get("forense"))

    with st.expander("Relatórios dos avaliadores e metadados"):
        st.json({
            "origem do texto do markdown": fraude.get("origem_markdown"),
            "fatos verificados por código": fraude.get("fatos"),
            "metadados do arquivo": fraude["metadata"],
            "avaliador textual": fraude["output_Textual_Evaluator"] or "não executado",
            "avaliador visual": fraude["output_Visual_Evaluator"] or "não executado",
            "avaliador de metadados": fraude["output_Metadata_Evaluator"] or "não executado",
            "orquestrador": orquestrador,
        }, expanded=1)


def situacao_do_identificador(identificador):
    """A pior situação entre as verificações do identificador."""
    situacoes = {verificacao["situacao"] for verificacao in identificador["verificacoes"]}
    for situacao in (identificadores_.INVALIDO, identificadores_.NAO_VERIFICAVEL, identificadores_.OK):
        if situacao in situacoes:
            return situacao
    return None


def mostrar_identificadores(identificadores):
    st.markdown("**Identificadores**")
    if not identificadores:
        st.caption("Nenhum identificador encontrado neste documento.")
        return

    invalidos = sum(situacao_do_identificador(identificador) == identificadores_.INVALIDO for identificador in identificadores)
    st.caption(f"{len(identificadores)} encontrados, {invalidos} com problema." if invalidos else f"{len(identificadores)} encontrados, nenhum com problema.")

    linhas = []
    for identificador in identificadores:
        detalhes = [verificacao["detalhe"] for verificacao in identificador["verificacoes"]]
        if identificador["no_texto"] is False:
            detalhes.append("Atenção: o valor apontado pela LLM não foi achado no texto extraído; confira no documento.")
        if not identificador["verificacoes"]:
            detalhes.append("Tipo sem verificador: só registrado." if not identificador["tem_verificador"] else "Nenhuma verificação se aplica a este valor.")
        linhas.append({
            "situação": SITUACOES_DO_IDENTIFICADOR.get(situacao_do_identificador(identificador), "— sem verificação"),
            "tipo": identificador["tipo"],
            "valor": identificador["valor"],
            "o que é": identificador["descricao"],
            "onde": identificador["localizacao"],
            "verificações": " ".join(detalhes),
        })
    st.dataframe(linhas, hide_index=True, width="stretch")


def mostrar_documento(resultado, markdown):
    document_type = resultado["document_type"]

    with st.container(border=True):
        st.markdown(f"**{resultado['arquivo']}** · tipo `{document_type}`")
        st.caption(resultado["classificacao"]["justificativa"])

        if document_type == OUTRO:
            st.info("Tipo não reconhecido: o documento não foi extraído, validado nem analisado.")
        else:
            coluna_extracao, coluna_validacao = st.columns(2)

            with coluna_extracao:
                st.markdown("**Informações extraídas**")
                if not resultado["document_information"]:
                    st.caption("Este tipo de documento ainda não tem campos no catálogo.")
                for extraction_type, campos in resultado["document_information"].items():
                    st.caption(f"Extração {extraction_type}")
                    linhas = [{"campo": campo, "valor": texto(valor)} for campo, valor in campos.items()]
                    st.dataframe(linhas, hide_index=True, width="stretch")

            with coluna_validacao:
                st.markdown("**Validações**")
                validacoes = resultado.get("dados_regras_subscricao")
                if validacoes is None:
                    st.caption("Clique em Validar para executar as validações.")
                elif not validacoes["subscription_validations"]:
                    st.caption("Não há validações escritas para este tipo de documento.")
                else:
                    st.dataframe(linhas_validacao(validacoes["subscription_validations"]), hide_index=True, width="stretch")

            if "identificadores" in resultado:
                mostrar_identificadores(resultado["identificadores"])

            if "fraude" in resultado:
                mostrar_fraude(resultado["fraude"])

        with st.expander("Markdown gerado pelo docling"):
            renderizado, bruto = st.tabs(["Renderizado", "Texto enviado à LLM"])
            with renderizado:
                # Sem o escape, valores como "R$ 1.000,00 ... R$ 2.000,00" seriam lidos como fórmula.
                # O docling marca com um comentário os pontos em que encontrou uma imagem
                st.markdown(markdown.replace("$", "\\$").replace("<!-- image -->", "*[imagem]*"))
            with bruto:
                st.code(markdown, language=None, wrap_lines=True)


def aba_proposta(catalogo):
    coluna_ficha, coluna_documentos = st.columns(2)

    with coluna_ficha:
        st.subheader("Ficha de cadastro")
        ficha_texto = st.text_area(
            "JSON da ficha de cadastro",
            value=EXEMPLO_FICHA_CADASTRO.read_text(encoding="utf-8"),
            height=380,
            help="Sem a ficha, as validações que dependem dela ficam aguardando o documento.",
        )
        ficha_cadastro, ficha_valida = None, True
        if ficha_texto.strip():
            try:
                ficha_cadastro = json.loads(ficha_texto)
            except json.JSONDecodeError as e:
                ficha_valida = False
                st.error(f"A ficha de cadastro não é um JSON válido: {e}")

    with coluna_documentos:
        st.subheader("Documentos")
        arquivos = st.file_uploader(
            "Imagens ou PDFs da proposta",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
        )
        st.caption(f"Tipos de documento no catálogo: {', '.join(catalogo) or 'nenhum'}")

        if st.button("Classificar e extrair", type="primary", disabled=not arquivos):
            try:
                classificar_e_extrair(arquivos, catalogo)
            except Exception as e:
                st.error(f"Não foi possível processar os documentos: {e}")

    resultados = st.session_state.get("resultados")
    if not resultados:
        return

    st.divider()
    coluna_validar, coluna_identificadores, coluna_fraude, coluna_baixar = st.columns([1, 1.5, 1, 3])
    with coluna_identificadores:
        if st.button(
            "Verificar identificadores", type="primary",
            help="Chama a LLM uma vez por documento. Ela localiza CPF, CNPJ, matrícula, linha digitável, Pix e outros números, e o código confere cada um.",
        ):
            try:
                with st.spinner(f"Buscando os identificadores com {MODEL_ID}..."):
                    verificar_identificadores_documentos(resultados, st.session_state["documentos"], catalogo, fraude_.carregar())
            except Exception as e:
                st.error(f"Não foi possível verificar os identificadores: {e}")
    with coluna_validar:
        # As validações não chamam a LLM: podem ser repetidas depois de alterar a ficha de cadastro
        if st.button("Validar", type="primary", disabled=not ficha_valida):
            validar_documentos(resultados, ficha_cadastro)
    with coluna_fraude:
        if st.button("Analisar fraude", type="primary", help="Chama a LLM de 1 a 4 vezes por documento, conforme o nível de risco do tipo."):
            try:
                with st.spinner(f"Analisando fraude com {MODEL_ID}..."):
                    analisar_fraude_documentos(resultados, st.session_state["documentos"], catalogo, fraude_.carregar())
            except Exception as e:
                st.error(f"Não foi possível analisar fraude: {e}")
    with coluna_baixar:
        st.download_button(
            "Baixar resultado (JSON)",
            data=json.dumps({"documentos": resultados}, indent=2, ensure_ascii=False),
            file_name="resultado.json",
            mime="application/json",
        )

    for resultado, documento in zip(resultados, st.session_state["documentos"]):
        mostrar_documento(resultado, documento.markdown)


# --- catálogo: tipos de documento e campos extraídos ---

def salvar(funcao, dados, aviso, selecionar=None):
    try:
        funcao(dados)
    except ValueError as e:
        st.error(str(e))
        return

    st.session_state["aviso"] = aviso
    st.session_state["selecionar"] = selecionar
    st.rerun()


def novo_tipo_de_documento(catalogo):
    with st.form("novo_tipo", clear_on_submit=True):
        st.markdown("**Novo tipo de documento**")
        nome = st.text_input("Label", placeholder="titulo_eleitor").strip()
        descricao = st.text_area(
            "Descrição para a classificação",
            placeholder="Título de eleitor. Contém nome, número de inscrição, zona, seção, data de nascimento ...",
        ).strip()
        risco = st.selectbox(
            "Nível de risco de fraude", fraude_.RISCOS, index=fraude_.RISCOS.index(fraude_.RISCO_PADRAO), format_func=ROTULOS_RISCO.get,
            help=AJUDA_RISCO,
        )

        if st.form_submit_button("Adicionar"):
            if nome in catalogo:
                st.error(f"O tipo '{nome}' já existe.")
            else:
                definicao = {
                    "descricao": descricao,
                    "risco": risco,
                    "instrucoes": {"textual": "", "visual": ""},
                    "instrucoes_fraude": dict.fromkeys(fraude_.PROMPTS, ""),
                    "campos": [],
                }
                salvar(catalogo_.salvar, {**catalogo, nome: definicao}, f"Tipo '{nome}' adicionado.", selecionar=nome)


def editar_tipo_de_documento(catalogo, document_type):
    definicao = catalogo[document_type]

    with st.form(f"editar_{document_type}"):
        descricao = st.text_area(
            "Descrição para a classificação",
            value=definicao["descricao"],
            key=f"descricao_{document_type}",
            help="É o que a LLM recebe para decidir se um documento é deste tipo.",
        )
        risco = st.selectbox(
            "Nível de risco de fraude",
            fraude_.RISCOS,
            index=fraude_.RISCOS.index(definicao.get("risco", fraude_.RISCO_PADRAO)),
            format_func=ROTULOS_RISCO.get,
            key=f"risco_{document_type}",
            help=AJUDA_RISCO,
        )

        st.markdown("**Campos extraídos**")
        campos = st.data_editor(
            pd.DataFrame(definicao["campos"], columns=COLUNAS_CAMPOS),
            num_rows="dynamic",
            hide_index=True,
            width="stretch",
            key=f"campos_{document_type}",
            column_config={
                "nome": st.column_config.TextColumn("Campo", required=True, help="Letras, números e _. É o nome usado pelas validações."),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=list(catalogo_.TIPOS), default="texto", required=True),
                "extracao": st.column_config.SelectboxColumn(
                    "Extração", options=list(catalogo_.EXTRACOES), default="textual", required=True,
                    help="textual: a LLM recebe o markdown. visual: recebe o markdown e o próprio arquivo.",
                ),
                "descricao": st.column_config.TextColumn("Info para a LLM", width="large", default="", help="O que deve ser respondido neste campo."),
            },
        )

        st.markdown("**Instruções do documento na extração**")
        instrucoes = {
            extraction_type: st.text_area(
                f"Extração {extraction_type}",
                value=definicao["instrucoes"].get(extraction_type, ""),
                height=180,
                key=f"instrucoes_{extraction_type}_{document_type}",
            )
            for extraction_type in catalogo_.EXTRACOES
        }

        st.markdown("**Instruções adicionais de fraude só para este documento**")
        st.caption(
            "Vão ao fim da prompt escolhida, depois das instruções gerais e das do nível de risco (aba Fraude). "
            "Servem para acrescentar ou dispensar uma regra neste tipo de documento. As que já vêm preenchidas são as "
            "regras que a referência trazia no texto da prompt para este documento: são uma primeira versão, para alterar."
        )
        instrucoes_fraude = campos_de_instrucoes(definicao.get("instrucoes_fraude"), f"fraude_{document_type}")

        st.markdown("**Arquivo esperado**")
        st.caption(
            "O que as validações do arquivo conferem neste tipo de documento, por código (aba Fraude). O que ficar em branco "
            "não é conferido. Preencha só o que vale para todo documento autêntico deste tipo: o que não bater gera uma flag "
            "com a severidade definida na aba Fraude e, se ela for crítica, o documento sai suspeito. Programas e assinatura "
            "só são conferidos em PDF que não é só imagem."
        )
        esperado = definicao.get("arquivo_esperado", {})
        coluna_formatos, coluna_programas = st.columns(2)
        formatos = coluna_formatos.multiselect(
            "Formatos em que o documento chega", list(forense_.FORMATOS), default=esperado.get("formatos", []),
            format_func=forense_.FORMATOS.get, key=f"formatos_{document_type}",
            help="Os formatos que o avaliador forense reconhece. Em branco, qualquer formato é aceito.",
        )
        programas = coluna_programas.text_input(
            "Programas que geram o PDF", value=", ".join(esperado.get("programas", [])), key=f"programas_{document_type}",
            help="Trechos do nome do programa gravado no PDF (Producer ou Creator), separados por vírgula. Exemplo: iText, PDFium.",
        )
        assinatura_digital = st.checkbox(
            "O documento é emitido com assinatura digital", value=esperado.get("assinatura_digital", False), key=f"assinatura_{document_type}",
        )
        certificados = st.text_area(
            "Certificados aceitos na assinatura", value="\n".join(esperado.get("certificados", [])), height=68, key=f"certificados_{document_type}",
            help="Impressão digital SHA-256 de cada certificado, uma por linha. Ela aparece no resultado da validação de assinatura "
                 "de um documento autêntico. Em branco, vale qualquer assinatura.",
        )

        if st.form_submit_button("Salvar", type="primary"):
            campos = campos.dropna(subset=["nome"]).fillna("")
            campos["nome"] = campos["nome"].str.strip()
            arquivo_esperado = {
                "formatos": formatos,
                "programas": [programa.strip() for programa in programas.split(",") if programa.strip()],
                "assinatura_digital": assinatura_digital,
                "certificados": [certificado.lower() for certificado in certificados.split()],
            }
            nova = {
                "descricao": descricao.strip(),
                "risco": risco,
                "instrucoes": instrucoes,
                "instrucoes_fraude": instrucoes_fraude,
                # só o que foi definido vai para o catálogo
                **({"arquivo_esperado": {chave: valor for chave, valor in arquivo_esperado.items() if valor}} if any(arquivo_esperado.values()) else {}),
                "campos": campos.to_dict("records"),
            }
            salvar(catalogo_.salvar, {**catalogo, document_type: nova}, f"Tipo '{document_type}' salvo.", selecionar=document_type)

    validations = VALIDACOES.get(document_type, {})
    with st.expander(f"Validações deste documento ({len(validations)})"):
        st.caption(
            "As validações vêm dos arquivos `*_validate.py` em `subscricao/validacoes/` e são recarregadas "
            "quando um arquivo muda. Os campos que elas esperam precisam existir no catálogo."
        )
        if validations:
            st.dataframe(
                [
                    {"validação": nome.removeprefix("validacao_"), "tipo": validation.tipo,
                     "espera": texto({descreve(documento): campos for documento, campos in validation.campos.items()})}
                    for nome, validation in validations.items()
                ],
                hide_index=True,
                width="stretch",
            )

    with st.popover("Excluir tipo de documento"):
        st.write(f"O tipo `{document_type}` deixa de ser classificado e extraído.")
        if st.button("Confirmar exclusão"):
            restante = {nome: valor for nome, valor in catalogo.items() if nome != document_type}
            salvar(catalogo_.salvar, restante, f"Tipo '{document_type}' excluído.")


def aba_catalogo(catalogo):
    pendencias = catalogo_.pendencias(catalogo)
    if pendencias:
        st.warning("Validações e catálogo não batem:\n\n" + "\n".join(f"- {p}" for p in pendencias))

    # A seleção feita ao adicionar um tipo precisa ser aplicada antes de o seletor ser criado
    selecionar = st.session_state.pop("selecionar", None)
    if selecionar in catalogo:
        st.session_state["tipo_selecionado"] = selecionar
    elif st.session_state.get("tipo_selecionado") not in catalogo:
        st.session_state.pop("tipo_selecionado", None)

    coluna_tipos, coluna_edicao = st.columns([1, 3])

    with coluna_tipos:
        document_type = st.radio("Tipo de documento", list(catalogo), key="tipo_selecionado") if catalogo else None
        novo_tipo_de_documento(catalogo)

    with coluna_edicao:
        if document_type is None:
            st.info("Adicione um tipo de documento para começar.")
        else:
            editar_tipo_de_documento(catalogo, document_type)


# --- fraude: avaliadores de cada risco e instruções adicionais ---

def avaliadores_por_risco(catalogo, config):
    st.subheader("Avaliadores de cada nível de risco")
    st.caption(
        "O nível de risco de cada tipo de documento é definido na aba Tipos de documento e campos. Ele escolhe a "
        "prompt do orquestrador e, pela tabela abaixo, quais avaliadores auxiliares rodam antes dele. No risco nulo "
        "o orquestrador nunca classifica o documento como suspeito, com ou sem avaliadores."
    )

    with st.form("avaliadores"):
        larguras = [1, 3, 1, 1, 1]
        cabecalho = st.columns(larguras)
        for coluna, titulo in zip(cabecalho, ["Risco", "Tipos de documento", *[ROTULOS_PROMPT[a] for a in fraude_.AVALIADORES]]):
            coluna.markdown(f"**{titulo}**")

        escolhidos = {}
        for risco in fraude_.RISCOS:
            linha = st.columns(larguras)
            linha[0].write(ROTULOS_RISCO[risco])
            documentos = [nome for nome, definicao in catalogo.items() if definicao.get("risco", fraude_.RISCO_PADRAO) == risco]
            linha[1].write(", ".join(documentos) or "nenhum")
            escolhidos[risco] = [
                avaliador
                for coluna, avaliador in zip(linha[2:], fraude_.AVALIADORES)
                if coluna.checkbox(
                    ROTULOS_PROMPT[avaliador],
                    value=avaliador in config["riscos"][risco].get("avaliadores", []),
                    key=f"avaliador_{risco}_{avaliador}",
                    label_visibility="collapsed",
                )
            ]

        if st.form_submit_button("Salvar avaliadores", type="primary"):
            nova = json.loads(json.dumps(config))
            for risco, avaliadores in escolhidos.items():
                nova["riscos"][risco]["avaliadores"] = avaliadores
            salvar(fraude_.salvar, nova, "Avaliadores salvos.")


def instrucoes_de_fraude(config):
    st.subheader("Instruções adicionais")
    st.caption(
        "Texto livre acrescentado ao fim de cada prompt, para somar ou dispensar regras sem editar a prompt. "
        "Valem para todos os documentos ou para um nível de risco; as de um documento específico ficam na aba "
        "Tipos de documento e campos. Em conflito, vale a mais específica."
    )

    escopos = {"geral": "Todos os documentos", **{risco: f"Documentos de risco {ROTULOS_RISCO[risco].lower()}" for risco in fraude_.RISCOS}}
    escopo = st.radio("Escopo", list(escopos), format_func=escopos.get, horizontal=True, key="escopo_instrucoes")
    atuais = config.get("instrucoes") if escopo == "geral" else config["riscos"][escopo].get("instrucoes")

    with st.form(f"instrucoes_{escopo}"):
        instrucoes = campos_de_instrucoes(atuais, f"instrucoes_fraude_{escopo}")

        if st.form_submit_button("Salvar instruções", type="primary"):
            nova = json.loads(json.dumps(config))
            if escopo == "geral":
                nova["instrucoes"] = instrucoes
            else:
                nova["riscos"][escopo]["instrucoes"] = instrucoes
            salvar(fraude_.salvar, nova, f"Instruções salvas ({escopos[escopo].lower()}).")


def previa_das_instrucoes(catalogo, config):
    st.subheader("O que vai para cada prompt")
    if not catalogo:
        st.caption("Adicione um tipo de documento para ver a prévia.")
        return

    coluna_documento, coluna_prompt = st.columns(2)
    document_type = coluna_documento.selectbox("Tipo de documento", list(catalogo), key="previa_documento")
    prompt = coluna_prompt.selectbox("Prompt", list(ROTULOS_PROMPT), format_func=ROTULOS_PROMPT.get, key="previa_prompt")

    definicao = catalogo[document_type]
    risco = definicao.get("risco", fraude_.RISCO_PADRAO)
    avaliadores = config["riscos"][risco].get("avaliadores", [])
    if prompt != "orquestrador" and prompt not in avaliadores:
        st.info(f"O {ROTULOS_PROMPT[prompt].lower()} não roda para documentos de risco {ROTULOS_RISCO[risco].lower()}.")
        return

    bloco = fraude_.instrucoes_adicionais(prompt, config, document_type, definicao)
    if bloco:
        st.caption(f"Bloco acrescentado ao fim da prompt ({document_type}, risco {ROTULOS_RISCO[risco].lower()}):")
        st.code(bloco, language=None, wrap_lines=True)
    else:
        st.caption("Sem instruções adicionais para esta prompt.")

    modelo = prompts_poc.ORQUESTRADOR[risco] if prompt == "orquestrador" else prompts_poc.AVALIADOR[prompt]
    with st.expander("Prompt completa"):
        st.caption("O texto fixo vem de `subscricao/fraude/prompts_poc.py`. Os campos entre chaves são preenchidos em cada análise.")
        st.code(modelo.replace("{{", "{").replace("}}", "}") + bloco, language=None, wrap_lines=True)


def regras_de_decisao(config):
    st.subheader("Regras de decisão")
    st.caption(
        "O orquestrador entrega as flags, cada uma com a sua severidade. O status sai destas regras: o documento fica "
        "suspeito quando alguma linha do nível de risco é atendida, isto é, quando há pelo menos aquela quantidade de "
        "flags de cada severidade. Sem nenhuma linha, o documento nunca fica suspeito. O fraud score é a soma dos pesos "
        "das flags (crítica 3, moderada 1, baixa 0,2) vezes o multiplicador, limitado a 10."
    )

    with st.form("decisao"):
        editadas = {}
        for risco in fraude_.RISCOS:
            decisao = fraude_.decisao_do_risco(config, risco)
            coluna_risco, coluna_multiplicador, coluna_regras = st.columns([1, 1, 3])
            coluna_risco.markdown(f"**{ROTULOS_RISCO[risco]}**")
            multiplicador = coluna_multiplicador.number_input(
                "Multiplicador do score", min_value=0.0, max_value=10.0, value=float(decisao["multiplicador"]), step=0.1, key=f"multiplicador_{risco}",
            )
            regras = coluna_regras.data_editor(
                pd.DataFrame(decisao["regras"], columns=list(ROTULOS_CONTAGEM)).fillna(0).astype(int),
                num_rows="dynamic",
                hide_index=True,
                key=f"regras_{risco}",
                column_config={
                    nome: st.column_config.NumberColumn(f"Mínimo de {rotulo}", min_value=0, step=1, default=0)
                    for nome, rotulo in ROTULOS_CONTAGEM.items()
                },
            )
            editadas[risco] = (multiplicador, regras)

        if st.form_submit_button("Salvar regras de decisão", type="primary"):
            nova = json.loads(json.dumps(config))
            for risco, (multiplicador, regras) in editadas.items():
                linhas = regras.fillna(0).astype(int).to_dict("records")
                nova["riscos"][risco]["decisao"] = {
                    "multiplicador": multiplicador,
                    # uma linha toda zerada tornaria todo documento suspeito: é descartada
                    "regras": [{nome: minimo for nome, minimo in linha.items() if minimo} for linha in linhas if any(linha.values())],
                }
            salvar(fraude_.salvar, nova, "Regras de decisão salvas.")


def sensibilidade_do_forense(config):
    st.subheader("Avaliador forense do arquivo")
    st.caption(
        "Análise algorítmica que depende só do formato em que o documento chegou (PDF gerado por software, digitalização, "
        "foto, print de tela), não do tipo de documento. O relatório dela vai para o avaliador visual. A sensibilidade é o "
        "limiar único de detecção: quanto maior, mais adulterações são sinalizadas, e mais documentos autênticos também."
    )

    sensibilidade = st.slider(
        "Sensibilidade de detecção", min(fraude_.SENSIBILIDADES), max(fraude_.SENSIBILIDADES), fraude_.sensibilidade_forense(config),
        help="0 não sinaliza nada; 10 sinaliza o máximo, com mais alarmes falsos.", key="sensibilidade_forense",
    )
    alarme_falso = forense_.ALARME_FALSO[sensibilidade]
    if alarme_falso:
        st.caption(f"Com {sensibilidade}, cerca de {100 * alarme_falso:g}% dos documentos autênticos recebem nível MODERADO ou ALTO.")
    else:
        st.caption("Com 0, nenhum documento é sinalizado: o relatório só informa as medidas.")

    calibracao = calibracao_forense.carregar()
    if calibracao.get("desempenho"):
        recomendada = calibracao.get("sensibilidade_recomendada")
        with st.expander(f"Desempenho medido na calibração (recomendada: {recomendada})"):
            st.dataframe(
                [{
                    "Sensibilidade": linha["sensibilidade"],
                    "Autênticos sinalizados": f"{100 * linha['alarme_falso_medido']:.1f}%",
                    "Fraudes do conjunto de teste sinalizadas": f"{100 * linha['deteccao']:.1f}%",
                    # só existe quando a calibração foi fechada com o estudo de adulterações sintéticas
                    "Adulterações sintéticas sinalizadas": f"{100 * linha['adulteracoes_sinteticas']:.1f}%" if "adulteracoes_sinteticas" in linha else "—",
                } for linha in calibracao["desempenho"]],
                hide_index=True,
            )
            st.caption(
                "Autênticos: validação cruzada nos documentos da calibração. Adulterações sintéticas: campo reescrito, trecho "
                "copiado ou colado e edição de PDF aplicados a páginas autênticas; inclui tipos que o avaliador não detecta."
            )

    if st.button("Salvar sensibilidade", type="primary"):
        nova = json.loads(json.dumps(config))
        nova.setdefault("forense", {})["sensibilidade"] = sensibilidade
        salvar(fraude_.salvar, nova, "Sensibilidade salva.")


def validacoes_do_arquivo(config):
    st.subheader("Validações do arquivo")
    st.caption(
        "Conferências de sim ou não feitas por código sobre o arquivo, sem calibração. A validação reprovada vira uma flag "
        "com a severidade escolhida aqui e entra nas regras de decisão; a informativa só aparece no resultado e é entregue ao "
        "orquestrador, que a avalia pelas regras da prompt. As três do tipo de documento usam o arquivo esperado definido na "
        "aba Tipos de documento e campos e contam como uma flag só, com a maior severidade entre elas."
    )
    severidades = fraude_.severidades_das_validacoes(config)

    with st.form("validacoes_do_arquivo"):
        escolhidas = {}
        for nome, funcao in validacoes_arquivo.VALIDACOES.items():
            coluna_validacao, coluna_severidade = st.columns([3, 1])
            coluna_validacao.markdown(f"**{funcao.titulo}**")
            coluna_validacao.caption(" ".join((funcao.__doc__ or "").split()))
            escolhidas[nome] = coluna_severidade.selectbox(
                "Flag quando reprovada", validacoes_arquivo.SEVERIDADES, index=validacoes_arquivo.SEVERIDADES.index(severidades[nome]),
                format_func=str.capitalize, key=f"severidade_{nome}",
            )

        if st.form_submit_button("Salvar validações do arquivo", type="primary"):
            nova = json.loads(json.dumps(config))
            nova.setdefault("forense", {})["validacoes"] = escolhidas
            salvar(fraude_.salvar, nova, "Validações do arquivo salvas.")


def verificacao_de_identificadores(config):
    st.subheader("Verificação de identificadores")
    st.caption(
        "A LLM localiza os identificadores de cada documento (CPF, CNPJ, matrícula de certidão, linha digitável, chave de "
        "acesso, Pix, endereços) e o código confere cada um. A maioria das verificações usa só o próprio valor. As que "
        "consultam serviços externos enviam a um terceiro um dado do documento, e só rodam se forem permitidas aqui."
    )
    opcoes = fraude_.identificadores(config)

    with st.form("identificadores"):
        consultas_externas = st.toggle("Permitir consultas externas", value=opcoes["consultas_externas"], key="consultas_externas")
        dominios = st.text_input(
            "Domínios de cobrança Pix que podem ser consultados", value=", ".join(opcoes["dominios_pix"]), key="dominios_pix",
            help="O endereço da cobrança vem de dentro do documento. A aplicação só consulta os domínios desta lista, separados por vírgula.",
        )
        if st.form_submit_button("Salvar verificação de identificadores", type="primary"):
            nova = json.loads(json.dumps(config))
            nova["identificadores"] = {
                "consultas_externas": consultas_externas,
                "dominios_pix": [dominio.strip().lower() for dominio in dominios.split(",") if dominio.strip()],
            }
            salvar(fraude_.salvar, nova, "Verificação de identificadores salva.")

    with st.expander("Verificadores disponíveis"):
        st.dataframe(
            [{
                "tipo": tipo,
                "verificador": nome,
                "o que confere": " ".join((funcao.__doc__ or "").split()),
                "informações que aceita": ", ".join(funcao.parametros) or "—",
                "consulta externa": "sim" if funcao.consulta_externa else "não",
            } for tipo, funcoes in identificadores_.VERIFICADORES.items() for nome, funcao in funcoes.items()],
            hide_index=True,
            width="stretch",
        )


def aba_fraude(catalogo, config):
    avaliadores_por_risco(catalogo, config)
    st.divider()
    regras_de_decisao(config)
    st.divider()
    verificacao_de_identificadores(config)
    st.divider()
    sensibilidade_do_forense(config)
    st.divider()
    validacoes_do_arquivo(config)
    st.divider()
    instrucoes_de_fraude(config)
    st.divider()
    previa_das_instrucoes(catalogo, config)


# --- regras de negócio: rascunho de validações a partir de um documento de regras ---

SITUACOES_DA_REGRA = {
    gerador.PRONTA: "✅ pronta",
    gerador.AMBIGUA: "❓ ambígua (comentada)",
    gerador.FALTA_INFORMACAO: "⏳ falta informação (comentada)",
}


def gerar_validacoes(arquivo, catalogo, ficha_cadastro, tipos):
    """Converte o documento de regras em markdown e pede à LLM o rascunho das validações."""
    with st.status("Lendo as regras de negócio...", expanded=True) as status:
        with tempfile.TemporaryDirectory(prefix="regras_", ignore_cleanup_errors=True) as pasta:
            path = Path(pasta) / arquivo.name
            path.write_bytes(arquivo.getvalue())
            st.write(f"Convertendo {arquivo.name} em markdown")
            documento = converter(path)
            st.write(f"Interpretando as regras com {MODEL_ID}")
            geracao = gerador.gerar(documento, catalogo, ficha_cadastro, tipos)
        status.update(label="Rascunho gerado", state="complete", expanded=False)

    st.session_state["geracao"] = geracao
    # o código e o nome do arquivo passam a ser os do rascunho novo
    st.session_state["codigo_das_regras"] = geracao["codigo"]
    st.session_state["arquivo_das_regras"] = geracao["nome_arquivo"]


def aba_regras_de_negocio(catalogo):
    st.caption(
        "Transforma um documento de regras de negócio em um rascunho de arquivo de validação. A LLM interpreta cada regra e "
        "propõe o código; você revisa, ajusta e salva. Regra ambígua ou sem informação suficiente entra comentada e não roda "
        "até a pendência ser resolvida. Nada é gravado nem executado antes de você salvar."
    )

    coluna_regras, coluna_ficha = st.columns(2)
    with coluna_regras:
        arquivo = st.file_uploader(
            "Documento com as regras de negócio", type=["pdf", "png", "jpg", "jpeg"], key="arquivo_de_regras",
            help="Formato livre. Costuma trazer um exemplo do documento e o texto dizendo o que deve ser conferido.",
        )
        tipos = st.multiselect(
            "Tipos de documento a considerar", list(catalogo), placeholder="Todos os tipos do catálogo", key="tipos_das_regras",
            help="Restringe os tipos de documento que as validações podem usar. Vazio, vale o catálogo inteiro.",
        )
    with coluna_ficha:
        ficha_texto = st.text_area(
            "Ficha de cadastro de exemplo (JSON)", value=EXEMPLO_FICHA_CADASTRO.read_text(encoding="utf-8"), height=230, key="ficha_das_regras",
            help="Mostra à LLM os campos da ficha com que os documentos podem ser comparados. Os valores não importam.",
        )
    try:
        ficha_cadastro = json.loads(ficha_texto)
    except json.JSONDecodeError as e:
        ficha_cadastro = None
        st.error(f"A ficha de cadastro de exemplo não é um JSON válido: {e}")

    if st.button("Gerar validações", type="primary", disabled=not arquivo or ficha_cadastro is None):
        try:
            gerar_validacoes(arquivo, catalogo, ficha_cadastro, tipos)
        except Exception as e:
            st.error(f"Não foi possível gerar as validações: {e}")

    geracao = st.session_state.get("geracao")
    if not geracao:
        return

    st.divider()
    regras = geracao["regras"]
    prontas = sum(regra["situacao"] == gerador.PRONTA for regra in regras)
    st.subheader(f"Regras de {geracao['origem']}")
    st.caption(f"{len(regras)} regras: {prontas} prontas e {len(regras) - prontas} pendentes, que entram comentadas no código.")
    st.dataframe(
        [{
            "nº": numero,
            "regra": regra["regra"],
            "onde": regra["localizacao"],
            "documento": regra["documento"],
            "situação": SITUACOES_DA_REGRA[regra["situacao"]],
            "pendência": regra["pendencia"],
        } for numero, regra in enumerate(regras, 1)],
        hide_index=True,
        width="stretch",
    )

    # As caixas perdem o conteúdo quando a aba deixa de ser exibida (no modo analista): o rascunho
    # guarda a última versão do que foi editado
    st.session_state.setdefault("codigo_das_regras", geracao["codigo"])
    st.session_state.setdefault("arquivo_das_regras", geracao["nome_arquivo"])
    codigo = st.text_area(
        "Código das validações", height=520, key="codigo_das_regras",
        help="É o texto do arquivo que será gravado. Para ativar uma regra pendente, resolva a pendência e retire o # das linhas do rascunho.",
    )
    nome_arquivo = st.text_input("Nome do arquivo em subscricao/validacoes/", key="arquivo_das_regras")
    geracao["codigo"], geracao["nome_arquivo"] = codigo, nome_arquivo

    problemas, avisos = gerador.conferir(codigo, catalogo, ficha_cadastro)
    for aviso in avisos:
        st.warning(aviso)
    if problemas:
        st.error("O código não pode ser salvo assim:\n\n" + "\n".join(f"- {problema}" for problema in problemas))
    else:
        st.success("Conferência do código sem problemas. A revisão continua sendo sua: confira se cada validação faz o que a regra pede.")

    if st.button("Salvar validações", type="primary", disabled=bool(problemas)):
        try:
            path = gerador.salvar(nome_arquivo, codigo, catalogo)
        except ValueError as e:
            st.error(str(e))
        else:
            for chave in ("geracao", "codigo_das_regras", "arquivo_das_regras"):
                st.session_state.pop(chave, None)
            st.session_state["aviso"] = f"Validações salvas em {path.name}. Para aplicá-las, clique em Validar na aba Proposta."
            st.rerun()


def main():
    st.set_page_config(page_title="Subscrição", layout="wide")

    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.title("Subscrição de documentos")
        # O modo vai para a URL (?modo=Desenvolvedor), então continua o mesmo ao recarregar a página
        modo = st.segmented_control(
            "Modo",
            [ANALISTA, DESENVOLVEDOR],
            default=ANALISTA,
            required=True,
            key="modo",
            bind="query-params",
            help="Analista: envia os documentos da proposta. Desenvolvedor: também altera os tipos de documento, as instruções das prompts e os avaliadores de fraude.",
        )

    aviso = st.session_state.pop("aviso", None)
    if aviso:
        st.toast(aviso)

    # Quem altera um arquivo de validação só precisa clicar em Validar de novo: os documentos já
    # extraídos continuam na tela e a LLM não é chamada
    try:
        if carregar_validacoes(apenas_se_alterado=True):
            st.toast("Validações recarregadas dos arquivos.")
    except Exception as e:
        st.error(f"Não foi possível carregar os arquivos de validação: {type(e).__name__}: {e}")

    catalogo = catalogo_.carregar()

    if modo != DESENVOLVEDOR:
        aba_proposta(catalogo)
        return

    config = fraude_.carregar()

    proposta, tipos, regras, fraude = st.tabs(["Proposta", "Tipos de documento e campos", "Regras de negócio", "Fraude"])
    with proposta:
        aba_proposta(catalogo)
    with tipos:
        aba_catalogo(catalogo)
    with regras:
        aba_regras_de_negocio(catalogo)
    with fraude:
        aba_fraude(catalogo, config)


main()
