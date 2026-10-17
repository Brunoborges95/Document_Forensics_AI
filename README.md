# POC de subscrição de documentos

Recebe a ficha de cadastro (JSON) e os documentos de uma proposta (imagens ou PDFs), descobre o
tipo de cada documento, extrai as informações, aplica as validações de subscrição e faz a análise
de fraude. Reaproveita o texto das prompts e as validações das lambdas em
`../projeto_unimed_subscrcao`. O catálogo tem os 26 tipos de documento que a referência extrai e
mais 13 acrescentados aqui; as validações existem para dois deles, RG e contrato social.

Tem duas formas de uso: uma tela (Streamlit) e a linha de comando.

## Fluxo

1. **Conversão** (`subscricao/conversao.py`): o docling converte cada documento em markdown.
2. **Classificação** (`subscricao/classificacao.py`): o Claude recebe o markdown e responde um dos
   tipos do catálogo ou `outro`. Documentos `outro` não seguem adiante.
3. **Extração** (`subscricao/extracao.py`): para cada tipo, o catálogo diz quais campos extrair.
   O Claude recebe uma prompt montada a partir desses campos e responde exatamente nesse formato.
   - Campos de extração `textual`: a LLM recebe só o markdown.
   - Campos de extração `visual`: a LLM recebe o markdown mais o próprio arquivo (PDF ou imagem),
     para a análise visual de assinaturas, selos, carimbos, marcas d'água e quadros.
4. **Validação** (`subscricao/validacoes/`): cada validação declara os documentos de que precisa e
   os campos esperados de cada um. A ficha de cadastro é um desses documentos; ela só não passa
   pela extração, porque já chega em JSON.
5. **Identificadores** (`subscricao/identificadores/`): a LLM localiza no documento os números
   com regra própria (CPF, CNPJ, matrícula de certidão, linha digitável, Pix e outros), e o
   código confere cada um.
6. **Fraude** (`subscricao/fraude/`): o código confere o arquivo (assinatura digital, programa
   gerador, formato), avaliadores auxiliares e um orquestrador apontam as anomalias do documento
   como flags, e as regras de decisão do nível de risco do tipo de documento dizem se ele é
   autêntico, suspeito ou inválido.

O que é dado e o que é código:

| | Onde fica | Como se altera |
|---|---|---|
| Tipos de documento, descrição para a classificação, nível de risco, campos, instruções e arquivo esperado | `catalogo.json` | pela tela, no modo desenvolvedor, na aba "Tipos de documento e campos" |
| Avaliadores e regras de decisão de cada nível de risco, sensibilidade do avaliador forense, severidade das validações do arquivo, instruções adicionais de fraude e opções da verificação de identificadores | `fraude.json` | pela tela, no modo desenvolvedor, na aba "Fraude" |
| Validações do arquivo | `subscricao/fraude/forense/validacoes.py` | em Python |
| Validações | `subscricao/validacoes/*_validate.py` | em Python |
| Verificadores de identificadores e consultas externas | `subscricao/identificadores/` | em Python |
| Texto fixo das prompts de fraude | `subscricao/fraude/prompts_poc.py` | em Python, por trocas sobre a cópia da referência (`prompts.py`) |

## Como rodar

O ambiente virtual fica fora do OneDrive, porque o docling instala alguns GB de dependências.

```powershell
C:\Users\bruno\anaconda3\python.exe -m venv $env:USERPROFILE\.venvs\subscricao-poc
& $env:USERPROFILE\.venvs\subscricao-poc\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # e preencha ANTHROPIC_API_KEY
```

O `pip` instala o PyTorch sem suporte a GPU. Em máquinas com placa NVIDIA, troque pela versão com
CUDA para o docling converter os documentos na GPU (na RTX 3070 desta máquina, cinco documentos
caíram de 142 s para 17 s). O docling passa a usar a GPU sozinho, sem mudança no código:

```powershell
& $env:USERPROFILE\.venvs\subscricao-poc\Scripts\python.exe -m pip install --force-reinstall --no-deps torch==2.14.1 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu126
```

### Tela

```powershell
.\iniciar.bat
```

O `iniciar.bat` equivale a rodar, de dentro desta pasta,
`& $env:USERPROFILE\.venvs\subscricao-poc\Scripts\python.exe -m streamlit run app.py`. Não use o
comando `streamlit` solto: no terminal ele costuma ser o do Anaconda, que não tem o docling nem as
versões de biblioteca do projeto. E rode de dentro desta pasta, senão o Streamlit não lê o
`.streamlit/config.toml`.

Abre em `http://localhost:8501`, acessível só desta máquina (para abrir na rede, altere
`.streamlit/config.toml`). Depois de alterar o código, reinicie o Streamlit; os arquivos de
validação são a exceção, porque a própria tela os recarrega.

A tela tem dois modos, escolhidos no seletor **Modo**, no alto à direita:

- **Analista** (o padrão): só a proposta. Envia a ficha e os documentos, valida, analisa fraude e
  vê os resultados. Não altera nada do catálogo nem da configuração de fraude.
- **Desenvolvedor**: a mesma proposta e mais as abas "Tipos de documento e campos", "Regras de
  negócio" e "Fraude", onde se adicionam documentos, se geram validações e se alteram as
  instruções das prompts e os avaliadores.

O modo vai para o endereço da página, então continua o mesmo ao recarregar. Para abrir direto no
modo desenvolvedor, use `http://localhost:8501/?modo=Desenvolvedor` (com a inicial maiúscula).
Trocar de modo não perde a proposta em andamento. O modo organiza a tela e não é controle de
acesso: qualquer pessoa que abra a tela pode trocá-lo.

- **Proposta**: cole a ficha de cadastro em JSON, envie os documentos e clique em
  **Classificar e extrair**. Depois:
  - **Validar** executa as validações. Não chama a LLM, então pode ser repetido depois de alterar
    a ficha ou um arquivo de validação.
  - **Analisar fraude** roda os avaliadores e o orquestrador de cada documento. Chama a LLM de 1 a
    4 vezes por documento, conforme o nível de risco.
  - **Verificar identificadores** localiza e confere os números do documento. Chama a LLM uma vez
    por documento.
  - O resultado pode ser baixado em JSON.
- **Tipos de documento e campos** (modo desenvolvedor): adiciona tipos (label, descrição para a
  classificação e nível de risco) e, para cada tipo, os campos a extrair: nome, tipo, extração
  (`textual` ou `visual`) e a informação que orienta a LLM. Também edita as instruções do
  documento na extração, as instruções adicionais de fraude só daquele documento e o arquivo
  esperado (formatos, programas geradores e assinatura digital), e mostra as validações que já
  existem para ele. Se validações e catálogo não baterem, a aba avisa.
- **Regras de negócio** (modo desenvolvedor): transforma um documento de regras de negócio em um
  rascunho de arquivo de validação, para revisar e salvar (seção "Gerar validações a partir das
  regras de negócio").
- **Fraude** (modo desenvolvedor): define quais avaliadores rodam e quais regras de decisão valem
  em cada nível de risco, a sensibilidade do avaliador forense, a severidade das validações do
  arquivo e as instruções adicionais gerais e por nível de risco, e mostra a prompt completa de
  cada documento. Também liga as consultas
  externas da verificação de identificadores e lista os verificadores disponíveis.

### Linha de comando

```powershell
& $env:USERPROFILE\.venvs\subscricao-poc\Scripts\python.exe main.py ..\docs\rg\<rg>.pdf ..\docs\contrato_social\<contrato>.pdf --ficha-cadastro exemplos\ficha_cadastro.json --fraude
```

O resultado é impresso e gravado em `saida/resultado.json`, ao lado do markdown de cada documento
(`saida/<nome do arquivo>.md`). Sem `--fraude`, a análise de fraude não é feita; a verificação
de identificadores entra com `--identificadores`.

A primeira execução baixa os modelos do docling e do OCR. `exemplos/ficha_cadastro.json` tem dados
fictícios e serve de modelo dos campos esperados; para as validações passarem, a ficha precisa
conter os dados dos documentos enviados. Sem a ficha, as validações que dependem dela retornam
`ESPERAR_DOCUMENTOS` e as demais rodam.

### Testes

Não chamam a API nem o docling:

```powershell
& $env:USERPROFILE\.venvs\subscricao-poc\Scripts\python.exe -m pytest
```

## Configuração

Variáveis de `.env` (todas opcionais, exceto a chave):

| Variável | Padrão | Uso |
|---|---|---|
| `ANTHROPIC_API_KEY` | | Chave da API da Anthropic |
| `MODEL_ID` | `claude-opus-5-5` | Modelo usado na classificação, nas extrações e na fraude |
| `LLM_EFFORT` | padrão do modelo | Profundidade de raciocínio: `low`, `medium`, `high`, `xhigh` ou `max` |
| `LLM_FALLBACKS` | `default` | Reexecuta em outro modelo as requisições recusadas. Vazio desliga |
| `OCR_LANG` | `iso:pt` | Idiomas do OCR do docling |

## Saída

```json
{
  "documentos": [
    {
      "arquivo": "contrato.pdf",
      "document_type": "contrato_social",
      "classificacao": {"document_type": "contrato_social", "justificativa": "..."},
      "document_information": {
        "textual": {"razao_social": "...", "cnpj": "...", "...": "..."},
        "visual": {"ha_assinatura": true, "descricao_assinatura": "...", "...": "..."}
      },
      "dados_regras_subscricao": {
        "subscription_validations": {
          "validacao_cnpj": {"valid": true, "tipo": "textual", "...": "..."},
          "validacao_ha_assinatura": {"valid": true, "tipo": "visual", "...": "..."}
        }
      },
      "fraude": {
        "nivel_risco": "MEDIO",
        "metadata": {"creator": "...", "producer": "...", "author": "...", "...": "..."},
        "forense": {
          "nivel": "BAIXO", "pontuacao": 1, "formatos": ["pdf_digital"], "...": "...",
          "validacoes": [
            {"validacao": "assinatura_integra", "titulo": "Assinatura digital íntegra", "situacao": "APROVADA",
             "detalhe": "1 assinatura(s) íntegra(s): ...", "dados": {"assinaturas": ["..."]}, "severidade": "CRÍTICA", "grupo": null}
          ]
        },
        "origem_markdown": "camada de texto do PDF (texto gravado no arquivo, sem OCR)",
        "fatos": {"cpfs": ["..."], "cpfs_invalidos": [], "cnpjs": ["..."], "cnpjs_invalidos": []},
        "output_Textual_Evaluator": {"textual_status": "CONSISTENTE", "...": "..."},
        "output_Visual_Evaluator": {"conclusao": "LEGÍTIMO", "...": "..."},
        "output_Metadata_Evaluator": "",
        "output_Evaluator": {
          "document_type": "Contrato Social", "impact_level": "MÉDIO",
          "status_fraude": "AUTÊNTICO", "fraud_score": 0.5,
          "decisao": {"contagem": {"criticas": 0, "moderadas": 1, "baixas": 0}, "regra": null},
          "evaluator_alignment": {"...": "..."},
          "flags": [{"category": "LAYOUT", "severity": "MODERADA", "source": "...", "description": "...", "evidence": "..."}],
          "reasoning_summary": "...",
          "valid": true, "fraud_errors": "OK"
        }
      },
      "identificadores": [
        {
          "tipo": "cnpj", "valor": "12.345.678/0001-95", "descricao": "CNPJ da empresa contratante",
          "localizacao": "página 1, preâmbulo", "origem": "texto", "no_texto": true, "tem_verificador": true,
          "verificacoes": [
            {"verificador": "cnpj_digito_verificador", "consulta_externa": false, "situacao": "OK", "detalhe": "...", "dados": {"...": "..."}}
          ]
        }
      ]
    }
  ]
}
```

`document_information` tem uma entrada por extração executada. Cada validação mantém o formato da
referência (`valid`, `target`, `trecho_procurado`, `trecho_encontrado`, `percent_match`,
`regras_subscricao_errors`) e ganha `tipo`. Em `fraude`, `output_Evaluator` junta a resposta do
orquestrador (flags, alinhamento e resumo) com o que o código decide (`status_fraude`,
`fraud_score` e `decisao`, que traz a contagem das flags e a regra atendida) e com `valid` e
`fraud_errors`, como na referência. Um avaliador que não rodou aparece como texto vazio.
`forense.validacoes` traz a situação de cada validação do arquivo (`APROVADA`, `REPROVADA`,
`NAO_SE_APLICA` ou `NAO_CONFERIDA`), o detalhe e a severidade da flag que a reprovada gera; essas
flags entram em `output_Evaluator.flags` com `source` igual a `VALIDACAO_DO_ARQUIVO`.
`identificadores` só existe quando a verificação de identificadores foi pedida: traz o que a LLM
achou e o resultado de cada verificador que rodou.

## Catálogo de documentos

`catalogo.json` tem uma entrada por tipo de documento:

```json
{
    "rg": {
        "descricao": "Registro Geral (RG), a carteira de identidade ...",
        "risco": "BAIXO",
        "instrucoes": {
            "textual": "O documento é o Registro Geral (RG) ...\nO nome de filiação do pai sempre vem primeiro que o nome da mãe.",
            "visual": ""
        },
        "instrucoes_fraude": {"orquestrador": "", "textual": "", "visual": "", "metadados": ""},
        "campos": [
            {"nome": "nome_mae", "tipo": "texto", "extracao": "textual", "descricao": "Filiacao Nome da Mae"}
        ]
    }
}
```

- `descricao` é o que a LLM recebe na classificação para reconhecer o tipo.
- `risco` (`ALTO`, `MEDIO`, `BAIXO` ou `NULO`) define como o documento passa pela análise de
  fraude.
- `instrucoes` são as orientações do documento em cada extração.
- `instrucoes_fraude` são instruções adicionais de fraude só para este documento, por prompt.
- `arquivo_esperado` (opcional) é o que as validações do arquivo conferem neste tipo: `formatos`
  em que ele chega, `programas` que geram o PDF, `assinatura_digital` e os `certificados` aceitos
  nela. O que não for definido não é conferido (seção "Validações do arquivo").
- Cada campo tem `nome` (o mesmo usado pelas validações), `tipo`, `extracao` e `descricao`, que
  diz à LLM o que responder. O nome não pode se repetir dentro do documento.
- Tipos de campo: `texto`, `booleano`, `inteiro` e dois compostos definidos em
  `subscricao/catalogo.py`: `endereco` (cep, rua, número, complemento, bairro, cidade, estado) e
  `lista_nome_cpf`.

### Tipos de documento que vieram da referência

Além de RG e contrato social, o catálogo tem os outros 24 tipos que a referência extrai, sem
validações. Cada entrada foi gerada das prompts de extração da referência (`information` para os
campos textuais, `signature` para os visuais): as instruções do documento e o texto de cada
pergunta foram copiados, e o nome de cada campo é o do `llm_to_object`. O que não veio de lá:

- **Descrição para a classificação**: é texto novo, porque a referência classifica com um modelo
  do DataRobot.
- **Regras gerais das prompts** (formato de data, `'Not Found'`, JSON de resposta): ficam em
  `prompts/extracao.json`. Saíram também as instruções sobre o Textract e sobre a confiança da
  assinatura detectada por ele.
- **Descrição dos campos `confianca_*`** e de `descricao_logo` e `descricao_brasao`, que a
  referência pede no modelo da resposta sem uma pergunta.
- **`gfip_novo`**: a referência lê esse documento pelos formulários e tabelas do Textract, sem
  prompt. Os campos têm como descrição o rótulo do formulário, e a primeira linha das instruções
  e a descrição da tabela de trabalhadores são novas.

Pontos em que a referência tinha algo estranho, e o que foi feito:

- **`gfd`**: a prompt descreve o documento como "Cartão de Plano", linha copiada da prompt do
  cartão. Aqui a primeira linha diz que é a Guia do FGTS Digital.
- **`contrato_estagio`**: a prompt visual é a do contrato social (quadro societário, Junta
  Comercial), mas o `llm_to_object` e a validação esperam os campos de assinatura do estagiário,
  da empresa e da instituição de ensino. Ficaram esses campos, sem instruções visuais.
- **`procuracao`**: falta o separador entre duas perguntas, e por isso a validade nunca era
  guardada. Aqui `validade` é um campo.
- **`requerimento_empresario`**: o `llm_to_object` não renomeia
  `ha_rodape_autenticacao_junta_digital`, que a validação espera como `ha_rodape_autenticacao`.
  Aqui o campo tem esse nome.
- **Perguntas sem campo**: `estatuto_social` e `procuracao` fazem uma pergunta cuja resposta a
  referência descarta. Viraram os campos `trecho_regras_assinatura` e `descricao_poderes`.
- **`ctps`**: quatro campos existem nas duas extrações com o mesmo nome. Ficaram na textual, e a
  visual tem só as duas assinaturas.

Campos que são listas ou dicionários na referência (beneficiários da carta de permanência,
cargos eleitos, departamentos e CPFs da ata, regras de assinatura do estatuto, trabalhadores da
relação do FGTS) estão como `texto`, que é o tipo que os dataclasses da referência declaram.
Respostas "True/False" e "Verdadeiro/Falso" das prompts de perguntas também ficaram como
`texto`. O `termo_reducao_carencia` não entrou, porque a referência não extrai dados dele.

### Tipos de documento acrescentados

Treze tipos não existem na referência. Entraram em 13/10/2026, todos com risco médio e sem
validações: carteira de identidade profissional (`carteira_identidade_profissional`), passaporte,
carteira de registro nacional migratório (`crnm`), comprovante do CPF (`comprovante_cpf`), cartão
do SUS (`cartao_sus`), holerite, contrato de trabalho (`contrato_trabalho`), termo de rescisão
(`termo_rescisao`), carta de concessão do INSS (`carta_concessao_inss`), comprovante de matrícula
(`comprovante_matricula`), declaração do imposto de renda (`declaracao_imposto_renda`), certidão
de óbito (`certidao_obito`) e termo de tutela ou curatela (`termo_tutela_curatela`).

A descrição, os campos e as instruções de extração foram escritos aqui, sem prompt da referência
nem documento de exemplo, e são uma primeira versão para o desenvolvedor ajustar. Todos os campos
são de extração textual, e as instruções adicionais de fraude vêm vazias. Com o modelo real só a
classificação foi exercitada em todos: um texto fictício de cada tipo novo e de seis tipos
vizinhos (RG, ficha de registro, termo de guarda, cartão CNPJ, certidão de nascimento e contrato
de estágio) foi classificado no tipo certo, 19 de 19. A extração e a análise de fraude só rodaram
para o holerite, em um documento fictício.

Para cada extração que tem campos, `subscricao/catalogo.py` monta um dataclass com esses campos.
A prompt enviada junta as regras gerais de `prompts/extracao.json` (formato de data, `'Not Found'`
etc.), as instruções do documento e a estrutura em JSON schema. A mesma estrutura é passada à API
como formato de resposta, o que garante um JSON válido com exatamente esses campos.

## Validações

As validações vêm de arquivos Python: todo `*_validate.py` em `subscricao/validacoes/` é carregado
automaticamente. Criar o arquivo basta; não há registro manual.

Uma validação não é classificada como subscrição ou fraude. Ela só indica o `tipo`: `textual`,
quando usa apenas campos da extração textual, ou `visual`, quando usa campos da extração visual.
A fraude vem da análise descrita mais abaixo.

### Regras prontas

Para os padrões mais comuns, uma linha registra a validação `validacao_<campo>`:

```python
# subscricao/validacoes/cnh_validate.py
from .regras import booleano, data_igual, data_recente, igualdade, similaridade

similaridade("cnh", "nome", limiar=90)            # parecido com o mesmo campo da ficha
igualdade("cnh", "cpf")                           # mesmos dígitos da ficha
igualdade("cnh", "cnpj", caracteres=r'[a-zA-Z0-9]')
data_igual("cnh", "data_nascimento")              # mesma data da ficha
data_recente("cnh", "data_emissao", anos=10)      # no máximo 10 anos
booleano("cnh", "ha_foto", confianca="confianca_foto", descricao="descricao_foto")
```

| Regra | Compara | Uso típico | Tipo padrão |
|---|---|---|---|
| `similaridade` | documento e ficha, por similaridade (`limiar` de 0 a 100) | nomes, razão social | textual |
| `igualdade` | documento e ficha, só os caracteres indicados (dígitos por padrão) | CPF, CNPJ | textual |
| `data_igual` | data do documento (DD-MM-YYYY) e da ficha (DD/MM/YYYY) | data de nascimento | textual |
| `data_recente` | data do documento contra hoje | validade, expedição | textual |
| `booleano` | campo sim/não com seus campos de confiança e descrição (`esperado=False` inverte) | respostas da análise visual | visual |

Todas aceitam `tipo=`. Elas reproduzem a lógica das validações equivalentes de RG e contrato social
da referência; os testes comparam os resultados das duas.

### Regras com lógica própria

O restante continua sendo uma função. O decorator diz a qual documento ela pertence e, para cada
documento de que ela precisa, quais campos espera:

```python
# compara o RG com a ficha de cadastro
@validacao("rg", campos={"ficha_cadastro": ["cpf"], "rg": ["cpf"]})
def validacao_cpf(ficha_cadastro, rg): ...

# usa um campo da extração visual
@validacao("contrato_social", campos={"contrato_social": ["ha_assinatura"]}, tipo="visual")
def validacao_ha_assinatura(contrato_social): ...

# pode usar quantos documentos precisar
@validacao("rg", campos={"ficha_cadastro": ["cnpj"], "rg": ["nome"], "contrato_social": ["socios", "cnpj"]})
def validacao_titular_e_socio(ficha_cadastro, rg, contrato_social): ...
```

- A função recebe um argumento por documento declarado, com o nome do documento, contendo só os
  campos declarados.
- Se um documento declarado não está disponível, a validação não executa e retorna
  `ESPERAR_DOCUMENTOS`, com a lista dos documentos que faltam em `trecho_encontrado`.
- Se um campo declarado não existe no documento, só aquela validação falha (`ERRO_INTERNO`).
- Por padrão, `trecho_procurado` vem da ficha de cadastro e `trecho_encontrado`, do documento ao
  qual a validação pertence; a função pode devolver os dois explicitamente.
- `@prepara_ficha_cadastro("rg")` marca o ajuste que a ficha de cadastro recebe antes das
  validações de um documento (no RG, os dados do responsável legal).

A terceira validação acima é só ilustração: nenhuma validação de RG ou contrato social da
referência usa outro documento além da ficha.

### Um entre vários documentos (condição OU)

Quando a regra aceita um entre vários documentos, uma tupla de tipos entra no lugar de um tipo.
Ela se lê como OU e vale em dois lugares:

```python
# o cônjuge pode ser comprovado pela certidão de casamento OU pela escritura de união estável
@validacao(("certidao_casamento", "escritura_uniao_estavel"),
           campos={"ficha_cadastro": ["nome"], ("certidao_casamento", "escritura_uniao_estavel"): ["nome"]})
def validacao_nome_conjuge(ficha_cadastro, certidao_casamento, escritura_uniao_estavel):
    documento = certidao_casamento or escritura_uniao_estavel
    ...

# o nome da mãe pode vir do RG OU da CNH
@validacao("comprovante_residencia", campos={"comprovante_residencia": ["nome"], ("rg", "cnh"): ["nome_mae"]})
def validacao_nome_da_mae(comprovante_residencia, rg, cnh): ...
```

- **No primeiro argumento**: a validação pertence a qualquer um dos tipos e roda para cada
  documento desses tipos que a proposta tiver, sempre com o documento que está sendo validado. Na
  primeira validação acima, uma certidão é validada como certidão, e a escritura, se também vier,
  como escritura.
- **Como chave de `campos`**: basta um dos tipos na proposta para a validação rodar. Sem nenhum,
  ela retorna `ESPERAR_DOCUMENTOS`, e `trecho_encontrado` diz o que serviria
  (`["rg ou cnh"]`).
- **Argumentos da função**: ela recebe um argumento por tipo da tupla. O que não está na proposta
  chega como `None`, como na referência, que recebia `None` no lugar do documento que faltava.
- **Campos**: a lista vale para todos os tipos da tupla. O aviso da tela confere se o catálogo
  extrai esses campos de cada um deles.

A tela "Regras de negócio" também escreve validações com OU.

### Gerar validações a partir das regras de negócio

Na aba "Regras de negócio" do modo desenvolvedor, a LLM lê um documento de regras escrito por
quem é do negócio e propõe o arquivo de validação. O desenvolvedor revisa o código, ajusta o que
for preciso e salva. O arquivo salvo é um `*_validate.py` como os outros: a fonte da verdade
continua sendo o código, e ele pode ser editado depois fora da tela.

1. Envie o documento de regras (PDF ou imagem), em formato livre. Ele costuma trazer um exemplo
   do documento e um texto dizendo o que conferir. A LLM recebe o texto e o próprio arquivo, o
   catálogo (tipos de documento e campos), a ficha de cadastro de exemplo, as regras prontas e os
   nomes das validações que já existem.
2. A tela mostra uma linha por regra, com o documento, a situação e a pendência, e o texto do
   arquivo. Cada validação vem com o texto da regra e a posição dela no documento em comentário.
3. A regra **pronta** entra como código, de preferência como regra pronta de uma linha. A regra
   **ambígua** ou com **falta de informação** (um prazo não informado, um campo que o catálogo
   não extrai, um tipo de documento que não existe) entra inteira em comentário, com a pendência
   explicada: não roda até alguém resolvê-la e tirar o `#`. Uma regra que a LLM marcou como pronta
   mas cujo rascunho não compila, ou tem reticências por preencher, também vai para comentário.
4. A cada edição a tela confere o código sem executá-lo e só libera **Salvar** sem problemas:
   sintaxe, imports e nomes fora do que uma validação usa, código solto no nível do arquivo,
   documento ou campo que não está no catálogo, nome repetido ou já usado em outro arquivo, e
   tipo `textual` ou `visual` incompatível com os campos. Campo da ficha de cadastro que não está
   na ficha de exemplo gera aviso, sem impedir.
5. **Salvar** grava o arquivo em `subscricao/validacoes/` e recarrega as validações. A tela não
   substitui um arquivo que já existe. Se o arquivo novo não carregar, ele é removido e as
   validações voltam a ser as de antes.

A conferência reduz o risco de salvar por engano um código que faz mais do que validar, mas não
é um isolamento: o código salvo roda dentro da aplicação, e o documento de regras é texto de
terceiros. Quem decide o que entra é o desenvolvedor que revisa. A geração não grava nem executa
nada.

A prompt está em `subscricao/gerador_de_validacoes.py`. Ela não supõe um formato para o documento
de regras e traz as convenções do sistema que evitam marcar tudo como ambíguo: nomes e razão
social por similaridade, CPF, CNPJ e datas por igualdade.

### Testar uma regra nova

Com a tela aberta e os documentos já extraídos, edite ou crie o arquivo de validação e clique em
**Validar** de novo. A tela recarrega os arquivos que mudaram e aplica as regras aos mesmos
documentos, sem reiniciar e sem chamar a LLM. Um erro de sintaxe no arquivo aparece no topo da tela.

## Verificação de identificadores

Um **identificador** é um valor que tem regra própria e aparece em qualquer documento: CPF, CNPJ,
matrícula de certidão, linha digitável, chave de acesso, código Pix, endereço de verificação. Uma
validação pertence a um tipo de documento e compara os campos extraídos dele; um **verificador**
pertence a um tipo de identificador e confere o valor em si, onde quer que ele apareça.

1. **Busca** (`busca.py`): a LLM recebe o documento e devolve os identificadores do texto, cada
   um com o tipo, o valor como está escrito, o que ele é naquele documento ("CPF do sócio
   administrador") e onde está. Os QR Codes são lidos por código, porque a LLM enxerga o código
   mas não o decodifica; a ela cabe dizer para que serve cada um. O que não se encaixa em nenhum
   tipo entra como `outro` (NIRE, protocolo, número de selo), só registrado.
2. **Verificação** (`verificadores.py`): cada identificador passa pelos verificadores do seu tipo.
   O resultado de cada um é `OK`, `INVALIDO` ou `NAO_VERIFICAVEL`, com o motivo e os dados que o
   próprio valor traz.

| Tipo | O que o verificador confere | Informações que aceita |
|---|---|---|
| `cpf` | 11 dígitos e dígitos verificadores | `cpf_esperado` (um ou vários) |
| `cnpj` | 14 caracteres e dígitos verificadores, inclusive no CNPJ alfanumérico | `cnpj_esperado` |
| `cnpj` (consulta externa) | existe na base da Receita e está ativo | `razao_social_esperada` |
| `pis` | 11 dígitos e dígito verificador | |
| `matricula_certidao` | 32 dígitos, dígitos verificadores, serviço de registro civil, ano do registro, tipo do livro | `tipo_certidao`, `ano_registro`, `data_nascimento` |
| `linha_digitavel` | dígitos verificadores de boleto (47) e de arrecadação (48); lê o valor e o vencimento | `valor_esperado`, `vencimento_esperado` |
| `chave_de_acesso` | 44 dígitos, dígito verificador, UF, mês, modelo e CNPJ do emitente | `cnpj_esperado`, `data_emissao` |
| `pix` | estrutura do código e código de controle; lê recebedor, valor e chave ou endereço da cobrança | `valor_esperado`, `recebedor_esperado` |
| `pix` (consulta externa) | a cobrança do Pix dinâmico existe na instituição recebedora | `valor_esperado`, `devedor_esperado` |
| `endereco` | de quem é o domínio: órgão público, entidade conhecida ou desconhecido. Não acessa o endereço | |

- **Informações de fora do documento** são parâmetros das funções. Sem elas, o verificador confere
  o que der com o valor; com elas, compara o que o valor diz com o esperado. É assim que o valor
  de um Pix é comparado com o valor de um pagamento: `valor_esperado` no contexto. O contexto é
  um dicionário com o nome do parâmetro, passado a `verificar_identificadores_documentos` ou,
  para um valor só, a `identificadores.verificar(tipo, valor, contexto)`, que pode ser chamada de
  dentro de uma validação.
- **Identificador mascarado** (`***.456.789-**`) não é inválido: sai como `NAO_VERIFICAVEL`. Com
  o valor esperado, os dígitos visíveis são comparados com ele. O CNPJ só com a raiz também é
  `NAO_VERIFICAVEL`. No CNPJ alfanumérico uma letra não é máscara.
- **Valor copiado errado**: se o valor que a LLM apontou não está no texto extraído, o
  identificador fica marcado (`no_texto: false`) e a tela avisa.
- **Consultas externas** enviam a um terceiro um dado do documento, e vêm desligadas. São
  ligadas na aba Fraude (`identificadores.consultas_externas` em `fraude.json`).

### Consultas externas

Ficam em `consultas.py`, separadas dos verificadores, para que o serviço consultado possa ser
trocado sem mexer na regra. Hoje são duas, com limite de 15 segundos cada:

| Consulta | Serviço | O que é enviado | O que volta |
|---|---|---|---|
| Cadastro do CNPJ | BrasilAPI, um espelho público da base da Receita (`CNPJ_URL`) | o CNPJ | razão social, situação cadastral, início de atividade, município e UF |
| Cobrança do Pix dinâmico | a instituição recebedora, no endereço que vem no código | só a requisição ao endereço | valor, vencimento, devedor e status da cobrança |

- **CNPJ**: o espelho público serve para a POC. Para volume ou garantia de serviço, o caminho é a
  base aberta da Receita hospedada pela própria aplicação, ou a API paga do Serpro: basta trocar
  `cadastro_cnpj`. O verificador dá `INVALIDO` para CNPJ que não existe ou não está ativo.
- **Cobrança Pix**: o endereço vem de dentro do documento, então um documento forjado poderia
  apontar para qualquer lugar. A aplicação só consulta por https, sem porta, usuário ou número de
  IP, e só os domínios da lista `dominios_pix` (de início, o da Caixa, das guias do FGTS
  Digital). Fora da lista, o resultado é `NAO_VERIFICAVEL`, sem nenhum acesso.
- **Respostas da cobrança**, pelo padrão do Banco Central: 404 é endereço que não exibe cobrança
  (`INVALIDO`); 410 é cobrança que existiu e não está mais disponível (`NAO_VERIFICAVEL`); 200
  traz a cobrança, que é comparada com `valor_esperado` e `devedor_esperado`.
- **Assinatura**: a cobrança vem assinada pela instituição recebedora, e essa assinatura não é
  conferida aqui. A garantia é a do https com o domínio permitido.
- **Serviço fora do ar ou lento**: o resultado é `NAO_VERIFICAVEL`, com o motivo. Nenhuma consulta
  torna um identificador inválido por não ter respondido.

### Acrescentar um verificador


Escreva a função em `verificadores.py`:

```python
@verificador("cpf", requer=("data_obito",))
def cpf_de_falecido(valor, data_obito): ...   # só roda quando o contexto traz data_obito

@verificador("titulo_eleitor")                # tipo novo: acrescente-o a TIPOS, em registro.py
def titulo_digito_verificador(valor, uf=None): ...
```

A função devolve `ok(...)`, `invalido(...)` ou `nao_verificavel(...)`, ou `None` quando não tem o
que dizer sobre aquele valor. `consulta_externa=True` marca a que sai da aplicação.

### O que foi conferido

Os algoritmos validaram os números reais que aparecem no texto dos
documentos de `docs/` (2.841 CPFs, 291 CNPJs, 413 PIS, 95 linhas digitáveis, 3 chaves de acesso
e 1 matrícula). Com LLM real, a busca rodou uma vez, em um documento fictício com 13
identificadores, e achou e classificou todos. A consulta de CNPJ foi feita uma vez na base
pública, com o CNPJ de uma empresa pública.

## Análise de fraude

Parte do `orchestrated_evaluator_B` de `b2b-doc-subs-fraud-detection-func`, que é o avaliador em
produção. Todas as chamadas à LLM recebem o próprio arquivo:

1. O **avaliador forense** mede o arquivo e roda as **validações do arquivo** (descritos mais
   abaixo), e o código confere o dígito verificador dos CPFs e CNPJs do texto (`fatos.py`).
2. Os **avaliadores auxiliares** habilitados para o nível de risco do documento rodam em seguida:
   - `textual`: consistência do texto, com o markdown como referência.
   - `visual`: layout e conferência das flags do relatório forense.
   - `metadados`: Producer, Creator, Author, Title e datas do PDF. Não roda para imagens.
3. O **orquestrador** recebe o markdown, os relatórios dos avaliadores e os metadados, e responde
   com as flags, cada uma com severidade (crítica, moderada ou baixa) e evidência localizada. Há
   uma prompt por nível de risco.
4. A **decisão** é feita em código (`decisao.py`): as regras do nível de risco transformam as
   flags do orquestrador e as das validações do arquivo reprovadas em `status_fraude`
   (`AUTÊNTICO`, `SUSPEITO` ou `INVÁLIDO`) e `fraud_score`.

### Prompts

`subscricao/fraude/prompts.py` é a cópia das seis prompts da referência. As prompts que a POC
envia estão em `subscricao/fraude/prompts_poc.py`, montadas a partir da cópia por trocas em
código: cada troca aponta o trecho original e o que entra no lugar, e a importação falha se o
trecho não existir mais. A aba Fraude mostra a prompt completa de cada documento. O que mudou:

| Motivo | O que mudou |
|---|---|
| Relatório forense genérico | A prompt visual vale para qualquer documento e aceita nível `N/A`. Em vez de obedecer ao nível do relatório, ela confere o ponto de cada flag: sobre campo crítico (nome, CPF, data, valor, assinatura) a flag fica; se todas caem sobre estrutura que se repete (linhas de tabela, código de barras, logotipo), o nível final é baixo. O que ela não localiza continua valendo. Saíram as métricas que o avaliador forense daqui não mede. |
| Markdown do docling | O markdown tem o marcador `--- PÁGINA N ---`, e as prompts informam a origem do texto. Lido por OCR, vale a regra da referência: priorizar o markdown e não concluir fraude por diferença de leitura. Vindo da camada de texto do PDF, um valor do markdown que não aparece na página, ou aparece diferente, é reportado como texto coberto ou reescrito. |
| Fatos conferidos por código | CPFs e CNPJs com dígito verificador inválido chegam prontos às prompts textual e do orquestrador. É flag crítica em texto da camada de texto do PDF; em texto de OCR é moderada, e só quando os dígitos estão legíveis na imagem. |
| Decisão em código | Saíram das prompts do orquestrador o cálculo do fraud score, a matriz de decisão, a regra de escalonamento e o JSON de saída. A resposta é estruturada, com as flags antes do resumo. |
| Regras por documento na tela | A tabela de producers por tipo de documento, a análise visual por tipo, a premissa dos documentos eletrônicos, o filtro da carta de não adesão e o filtro de software de edição gráfica saíram do texto e viraram instruções iniciais (seção "Instruções adicionais"). |
| Regras que se contradiziam | Na textual, a troca de acentuação e o truncamento de nome estavam na lista do que reportar e na do que não reportar: saíram da primeira. No orquestrador, estados civis contraditórios eram "crítica sempre" na etapa 1 e moderada na etapa 2: vale a moderada. A regra eliminatória mandava contar CPFs: agora conta documentos, e vários CPFs no mesmo documento não o invalidam. |
| Documento não é instrução | As prompts dizem que o conteúdo do documento é dado a analisar, e texto dirigido ao avaliador vira flag crítica. O markdown não consegue fechar a marcação em que é enviado. |
| Validações do arquivo | O orquestrador recebe as validações do arquivo reprovadas. As que têm severidade já entram na decisão por código, e a prompt pede que ele não gere outra flag para o mesmo fato; as informativas ficam para ele avaliar pelas regras da prompt. As aprovadas não vão, para não pesarem a favor do documento. |

Nenhuma destas mudanças foi medida com documentos reais. Com LLM real, o fluxo só rodou em
documentos fictícios (seção "Limitações conhecidas").

### Níveis de risco e regras de decisão

São quatro. Em três o documento é avaliado, com tolerância crescente; no nulo ele nunca é
classificado como suspeito. O risco de cada tipo de documento fica no catálogo, e `fraude.json`
diz, para cada nível, quais avaliadores rodam e com que regras as flags viram status:

| Risco | Avaliadores | O documento sai `SUSPEITO` com | Fraud score | Tipos de documento |
|---|---|---|---|---|
| `ALTO` | textual, visual e metadados | 1 flag crítica, 2 moderadas, ou 1 moderada e 3 baixas | soma dos pesos × 1,0 | CTPS, GFD, comprovante de pagamento da GFD, eSocial, relação de trabalhadores do FGTS, carta de permanência, cartão do plano, comprovante de residência |
| `MEDIO` | textual e visual | 1 flag crítica ou 3 moderadas | soma dos pesos × 0,5 | ficha de registro, nota fiscal, contrato de prestação de serviço, certidão de casamento, escritura de união estável, contrato social, procuração, carta de não adesão e os 13 tipos acrescentados |
| `BAIXO` | textual | 1 flag crítica | soma dos pesos × 0,1 | contrato de estágio, requerimento de empresário, MEI, ata de assembleia, estatuto social, certidão de nascimento, RG, CNH, cartão CNPJ, termo de guarda |
| `NULO` | nenhum | nunca | 0 | nenhum |

Os pesos são os da referência: crítica 3, moderada 1 e baixa 0,2, com a soma limitada a 10. Em
qualquer nível, um arquivo com mais de um documento sai `INVÁLIDO`, com score 10. As regras de
decisão e o multiplicador de cada nível são editados na aba Fraude: cada linha de regra é uma
combinação de quantidades mínimas, e basta uma linha atendida. Os valores de `ALTO` e `MEDIO`
repetem a matriz que a referência escrevia na prompt, e nesses dois níveis a distribuição dos
tipos de documento é a das listas de risco da lambda de fraude.

Os dez tipos que a referência trata como baixo risco ficaram em `NULO` até 13/10/2026, quando
passaram a `BAIXO`: agora o avaliador textual roda para eles, e uma flag crítica os torna
suspeitos. Nenhum tipo do catálogo está em `NULO`; o nível continua disponível na tela.

A referência tem três níveis, e no baixo o status é sempre `AUTÊNTICO`: esse é o `NULO` daqui,
com a mesma prompt e o nome do nível trocado. O `BAIXO` daqui não existe na referência. A prompt
dele é a de médio risco com duas diferenças, ambas tiradas de outras prompts da referência:
variação em campo identificador (a grafia de um nome, por exemplo) é flag moderada, e não
crítica; e, sem evidência clara e objetiva de adulteração, o documento não recebe flag crítica.

Duas diferenças de comportamento vêm de a decisão ter saído da prompt:

- A regra de escalonamento não existe mais. Ela tornava o documento suspeito por inconsistência
  textual em campo identificador, por nível moderado ou alto do avaliador visual e por
  `PROVÁVEL ADULTERAÇÃO` nos metadados. Os três casos continuam gerando flag crítica, que leva ao
  mesmo resultado. A exceção é o `SUSPEITO` do avaliador de metadados no risco médio, que
  escalava sozinho e agora conta como flag moderada (esse avaliador vem desligado nesse nível).
- Sem o avaliador visual, o relatório forense não chega ao orquestrador: no risco baixo ele só
  aparece na tela, a menos que o avaliador visual seja ligado para esse nível. As validações do
  arquivo não dependem disso: entram na decisão em todo nível que tenha regras de decisão.

### Instruções adicionais

Para acrescentar ou dispensar uma regra sem mexer no código, escrevem-se instruções em texto
livre no modo desenvolvedor da tela, por prompt (orquestrador, textual, visual ou metadados), em
três escopos:

| Escopo | Onde se edita | Exemplo |
|---|---|---|
| Todos os documentos | aba Fraude | "Considere 2026 como ano corrente." |
| Um nível de risco | aba Fraude | Em risco alto, no avaliador de metadados: "Considere o Producer 'Acme PDF' legítimo para comprovante de residência." |
| Um tipo de documento | aba Tipos de documento e campos | Em contrato social, no orquestrador: "Não aplique a regra de data futura a este documento." |

As instruções vão em um bloco ao fim da prompt, do escopo mais geral para o mais específico, com
a orientação de que prevalecem sobre as regras anteriores e de que o formato de saída não muda.
A aba Fraude mostra o bloco e a prompt completa de cada documento.

Algumas já vêm preenchidas. São os trechos que a referência trazia no texto das prompts e que só
valem para um tipo de documento ou um nível de risco, copiados para cá como primeira versão, para
o desenvolvedor alterar:

| Instrução inicial | Onde está |
|---|---|
| Producers e creators esperados | metadados de carta de permanência, cartão do plano, eSocial, relação de trabalhadores do FGTS, CTPS, GFD, comprovante de pagamento da GFD e comprovante de residência |
| Análise visual do tipo de documento | visual de eSocial, carta de permanência, relação de trabalhadores do FGTS e cartão do plano (formatos A a D e regra da capa decorativa) |
| Premissa dos documentos eletrônicos | orquestrador de carta de permanência, eSocial, relação de trabalhadores do FGTS e cartão do plano |
| Filtro de contexto da carta de não adesão | orquestrador da carta de não adesão |
| Filtro de software de edição gráfica nos metadados | orquestrador dos riscos médio e baixo |

Na cópia saíram as linhas "Relatório técnico MODERADO/ALTO → SUSPEITO", que contrariam a
conferência das flags, a menção a RAG e os nomes de métricas que o avaliador forense daqui não mede.

### Avaliador forense do arquivo

O relatório técnico que o avaliador visual recebe vem de `subscricao/fraude/forense/`. Ele
substitui o `visual_analysis.py` da referência, que tinha limiares por tipo de documento, por um
avaliador que depende só do **formato em que o documento chegou** e de **um limiar**, a
sensibilidade.

1. **Formato de cada página** (`formato.py`):

   | Formato | O que é | O que é examinado |
   |---|---|---|
   | `pdf_digital` | PDF gerado por software, com texto vetorial | estrutura do arquivo |
   | `pdf_sem_texto` | PDF vetorial com as letras em curvas | só anotações |
   | `digitalizacao` | papel digitalizado, com ruído | pixels e o que foi desenhado por cima no PDF |
   | `foto` | fotografia do documento | idem |
   | `imagem_limpa` | imagem sem ruído de papel (gerada por software ou limpa pelo scanner) | copy-move e o que foi desenhado por cima no PDF |
   | `captura_de_tela` | print de tela | só o que foi desenhado por cima no PDF |
   | `bitonal` | preto e branco puro | idem |

   Página de PDF dominada por uma imagem é tratada pela imagem. Em print de tela, preto e branco
   puro e PDF sem texto, nada da página em si pode ser medido: o nível só existe quando há algo
   desenhado por cima dela no PDF. Sem isso o nível vem `N/A`, e não `BAIXO`, para que "sem
   medida" não seja lido como "sem problemas"; a decisão fica com a inspeção visual. O resultado
   traz também o `alcance` da análise (`normal`, `limitado` na imagem sem ruído, `nenhum`), que
   a tela mostra junto do nível.

2. **Sinais** de cada formato:
   - Pixels (`raster.py`, OpenCV): `campo_liso`, o campo reescrito por cima da imagem (o retângulo
     pintado não tem o ruído do papel ao redor), e `copia_interna`, o copy-move (pontos SIFT casados
     com os da própria página, agrupados pelo deslocamento comum e confirmados pela correlação do
     ruído entre os dois trechos: letras iguais se repetem em qualquer documento, o ruído não).
   - Estrutura do PDF (`estrutura.py`, pdfium): texto coberto por forma opaca e reescrito
     (`texto_substituido`, `texto_oculto`), trecho em fonte não embutida, em segunda versão de uma
     fonte que a página já usa ou em tamanho quase igual ao do restante, anotações que desenham
     conteúdo e, em página digitalizada, texto, forma ou imagem desenhados por cima da imagem.
     O relatório cita o que foi encontrado, por exemplo `'R$ 1.200,00' coberto e reescrito como
     'R$ 4.360,00'`.

3. **Raridade** (`calibracao.py`): cada valor é comparado com a distribuição do mesmo sinal em
   páginas autênticas do mesmo formato (`calibracao.json`). A raridade do documento é a fração
   dos autênticos com sinais tão raros quanto os dele.

4. **Sensibilidade**, de 0 a 10, na aba Fraude (`forense.sensibilidade` em `fraude.json`): é a
   fração de documentos autênticos que se aceita sinalizar. Documento mais raro que o limiar
   recebe `MODERADO`; cinco vezes mais raro, `ALTO`.

   | Sensibilidade | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
   |---|---|---|---|---|---|---|---|---|---|---|---|
   | Autênticos sinalizados (nominal) | 0% | 0,2% | 0,5% | 1% | 2% | 3% | 5% | 8% | 12% | 20% | 30% |
   | Autênticos sinalizados (medido) | 0% | 0% | 0,4% | 2,6% | 3,9% | 5,1% | 6,7% | 8,4% | 10,5% | 15,8% | 22,3% |
   | Adulterações sintéticas sinalizadas | 0% | 0% | 0% | 3% | 12% | 13% | 14% | 29% | 44% | 49% | 60% |

   O padrão é **8**: é onde a diferença entre detecção e alarme falso praticamente para de
   crescer (33 pontos em 8 e em 9, 38 em 10, com o dobro de alarmes falsos).

O casamento de descritores do copy-move usa a GPU pelo torch quando há CUDA (`FORENSE_GPU=0`
desliga). O OpenCV do pip não traz CUDA, e o OpenCL dele não rendeu nessas operações. O casamento
fica cerca de 30 vezes mais rápido, mas a análise da página inteira ganha pouco, porque a
detecção dos pontos SIFT, na CPU, domina o tempo (1 a 3 s por página digitalizada; PDF gerado por
software leva centésimos de segundo).

#### Validações do arquivo

Os sinais acima medem rastro de edição e dependem de calibração. As validações do arquivo
(`forense/validacoes.py`) são conferências de sim ou não, com critério fixo. Cada uma é uma
função registrada com `@validacao`, e o resultado de todas vai em `forense.validacoes`, com a
situação (`APROVADA`, `REPROVADA`, `NAO_SE_APLICA` ou `NAO_CONFERIDA`) e o detalhe. A tela mostra
a tabela junto do nível forense.

| Validação | Aprovada quando | Flag padrão |
|---|---|---|
| `assinatura_integra` | em PDF assinado, o conteúdo coberto por cada assinatura é o mesmo de quando foi assinado | crítica |
| `datas_dos_metadados` | a criação e a modificação do PDF não estão no futuro, e a modificação não é anterior à criação | moderada |
| `gerado_por_ia` | o arquivo não declara, nos metadados ou nas credenciais de conteúdo (C2PA), ter sido gerado por IA, nem traz o bloco de texto que os geradores gravam | crítica |
| `editado_com_ia` | o arquivo não declara ter sido editado com IA | moderada |
| `programa_de_edicao` | o programa gravado nos metadados (do PDF, ou EXIF e XMP da imagem) não é um editor gráfico | informativa |
| `formato_esperado` | o arquivo chegou em um dos formatos que o tipo de documento espera | crítica |
| `programa_esperado` | o programa que gerou o PDF é um dos que o tipo de documento espera | crítica |
| `assinatura_esperada` | o PDF tem a assinatura digital com que o tipo é emitido, de um dos certificados aceitos | crítica |

Como o resultado é usado:

- **Flag por código**: a validação reprovada vira uma flag com `source` igual a
  `VALIDACAO_DO_ARQUIVO`, que se soma às do orquestrador nas regras de decisão. A severidade de
  cada validação é escolhida na aba Fraude (`forense.validacoes` em `fraude.json`).
- **Informativa**: não vira flag. Vai para o resultado e para o orquestrador, que a avalia pelas
  regras da prompt. É o padrão do programa de edição gráfica, porque a regra dos riscos médio e
  baixo sobre esse tipo de programa é uma instrução do orquestrador.
- **Uma flag só para o tipo de documento**: as três últimas comparam o arquivo com o
  `arquivo_esperado` do tipo no catálogo e descrevem o mesmo fato, o arquivo não ser o que o
  emissor entrega. Reprovadas juntas, viram uma flag, com a maior severidade entre elas.
- **O arquivo fora do esperado decide sozinho**: desde 13/10/2026 essas três saem como flag
  crítica, que basta para o documento ficar suspeito em qualquer nível de risco com regras de
  decisão. Antes eram moderadas e dependiam de outro indício, que vinha da LLM em uma rodada e
  não vinha na seguinte. Para voltar a exigir outro indício, troque a severidade na aba Fraude.
- **PDF que é só imagem**: o programa gerador e a assinatura não são conferidos em papel
  digitalizado, foto ou print guardado em PDF, porque ali o programa é o do scanner e o papel
  não carrega assinatura digital (é o caso da carteira de trabalho física). Se o tipo de
  documento não pode chegar assim, quem reprova é o formato esperado.
- **Risco sem regras de decisão** (o nulo): nenhuma flag é gerada; as validações só informam.
- **Orquestrador**: recebe só as reprovadas, com a orientação de não repetir como flag o que já
  foi contado. As aprovadas não vão: uma conferência que não achou problema não deve pesar a
  favor do documento.

A leitura das assinaturas usa o pyHanko, sem acessar a rede; sem ele, as duas validações de
assinatura ficam como não conferidas. A assinatura é conferida quanto à integridade e ao
certificado que assinou, não quanto à cadeia de confiança: qualquer pessoa cria um certificado
com o nome que quiser, e por isso o catálogo lista os certificados aceitos pela impressão digital
(SHA-256), que o resultado da validação mostra.

O arquivo esperado já vem preenchido em três tipos, com o que a amostra mostrou. A coluna dos
autênticos é o alarme falso da flag "arquivo fora do esperado":

| Tipo | Arquivo esperado | Autênticos com a flag | Fraudes com a flag |
|---|---|---|---|
| CTPS | programas iText, PDFium ou Skia; assinatura digital do certificado da Dataprev | 3 de 20 | 4 de 5 |
| Carta de permanência | PDF gerado por software | 1 de 20 | 2 de 4 |
| GFD | programas iText, JasperReports, Print To PDF, PDFium, Skia, Ghostscript, QuickReports ou Bullzip | 0 de 43 | 0 de 2 |

As 43 guias são as do FGTS Digital e as guias antigas (pastas `gfd`, `grf_nova` e `grf`). O tipo
de cada fraude foi atribuído pelo nome do arquivo e pelo texto; 7 das 29 ficaram sem tipo.
Somando os três tipos, a flag aparece em 4 de 83 autênticos e em 6 de 11 fraudes. Como ela é
crítica, esses são os documentos que saem suspeitos só por ela, sem depender da LLM.

O que a medição mostrou (13/10/2026, nos 821 arquivos de `docs/`, nas 29 fraudes e em 6
documentos fictícios gerados por código):

- **Assinatura quebrada**: a validação reprovou os 3 contratos assinados da pasta
  `contrato-prestacao-servicos-modif`, que são contratos alterados, e nenhum dos outros 63 PDFs
  assinados. Um PDF o pyHanko não conseguiu ler.
- **Acréscimo depois da assinatura não é sinal**: aparece em contratos autênticos assinados em
  plataforma (DocuSign, gov.br), e por isso só a quebra da assinatura reprova.
- **CTPS**: as 17 assinadas usam o mesmo certificado, autoassinado, da Dataprev, válido de 2019 a
  2029. As 3 autênticas sem assinatura são reimpressões pelo navegador. A única CTPS assinada do
  conjunto de fraudes tem a assinatura íntegra desse certificado: o arquivo é o original do
  aplicativo, e o que há de errado com ela não está no arquivo.
- **Datas e marcas de IA**: nenhuma reprovação em 856 arquivos. As marcas de IA seguem o padrão
  IPTC e os blocos dos geradores mais comuns, e não foram exercitadas com arquivos reais de
  gerador de imagem. A ausência da marca não prova nada: ela some com um print de tela.
- **Programa de edição gráfica**: 5 autênticos (4 PDFs do Canva e 1 imagem do PhotoScape) e
  nenhuma fraude.
- **Guias antigas**: uma lista de programas tirada só das guias do FGTS Digital reprovaria 11
  das 20 guias antigas (GRF) da amostra, que saem de impressoras de PDF e do programa da própria
  guia. A lista do catálogo inclui esses programas.
- **Fictícios**: a CTPS feita com o Chrome sem interface, a guia do FGTS sem programa gerador e a
  carta de permanência em imagem recebem a flag e saem suspeitas por ela; a carta em PDF feita
  com o ReportLab não, porque as cartas autênticas saem de muitos programas e não há lista que
  as separe. Com o modelo real, quando a flag ainda era moderada, ela foi a única que a guia e a
  carta em imagem receberam, e as duas continuaram autênticas.

O que foi medido e ficou de fora:

- **Revisões do PDF e data de modificação diferente da de criação**: aparecem na mesma proporção
  em autênticos e em fraudes.
- **Formato esperado para a GFD**: 9 das 20 autênticas chegam como imagem.
- **Lista de programas para carta de permanência, comprovante de residência e comprovante de
  pagamento**: cada emissor usa um programa, e uma lista tirada de 20 documentos recusaria os
  emissores que não estão neles.

Limites:

- **Metadados são de quem gera o arquivo**: o nome do programa e as datas pegam o documento
  refeito sem cuidado, não o que foi feito para enganar. A assinatura de certificado aceito é a
  única dessas conferências que não se falsifica.
- **A lista de programas é a da amostra**: um documento autêntico gerado por um programa que não
  está na lista do tipo sai suspeito, até o programa ser acrescentado na tela. Nas guias do FGTS
  isso é provável, porque elas passam por impressoras de PDF de todo tipo.
- **Certificado da CTPS**: os 17 exemplos assinados são de setembro de 2023 a fevereiro de 2024.
  Se a Dataprev passou a assinar com outro certificado depois disso, uma CTPS autêntica recente
  sai suspeita. Falta conferir com uma CTPS emitida agora; o resultado da validação mostra a
  impressão digital do certificado, para acrescentar à lista.
- **Amostras pequenas**: 20 documentos por tipo. Os alarmes falsos da tabela são os da amostra,
  e fora dela tendem a ser maiores.
- **Severidade única**: a severidade é da validação, não do tipo de documento. Um tipo de risco
  médio ou baixo que ganhe arquivo esperado também fica suspeito com uma reprovação.

Para acrescentar uma validação, escreva em `forense/validacoes.py` uma função que recebe o
`Arquivo` e devolve `aprovada(...)`, `reprovada(...)`, `nao_se_aplica(...)` ou
`nao_conferida(...)`:

```python
@validacao("pdf_sem_javascript", "PDF sem JavaScript", "PDF com JavaScript embutido", BAIXA)
def pdf_sem_javascript(arquivo):
    """O PDF não traz código JavaScript embutido."""
    if not arquivo.eh_pdf:
        return nao_se_aplica("Só PDF pode trazer JavaScript.")
    if b"/JavaScript" in arquivo.dados:
        return reprovada("O PDF traz código JavaScript embutido.")
    return aprovada("O PDF não traz JavaScript.")
```

Ela passa a aparecer no resultado, na tela e na lista de severidades da aba Fraude.

#### O que o estudo mediu

Base: 829 documentos de `docs/` tratados como autênticos (não conferidos um a um), 29 fraudes de
`docs_fraude_QA/` e adulterações sintéticas aplicadas a páginas autênticas. Detecção na
sensibilidade 8 (controle é a mesma página sem adulteração):

| Adulteração | PDF digital | Digitalização | Foto | Imagem limpa |
|---|---|---|---|---|
| Controle | 14% | 11% | 13% | 7% |
| Retângulo e texto por cima, no PDF | 100% | | | |
| Caixa de texto (anotação) | 100% | | | |
| Trecho reescrito em fonte padrão | 62% | | | |
| Trecho reescrito na mesma fonte, tamanho levemente diferente | 15% | | | |
| Campo reescrito, arquivo salvo sem perda | | 89% | 73% | 2% |
| Campo reescrito, arquivo regravado em JPEG | | 24% | 20% | 11% |
| Campo reescrito com desfoque e ruído parecidos | | 11% | 16% | 7% |
| Trecho copiado da própria página | | 71% | 38% | 31% |
| Trecho colado de outro documento | | 13% | 18% | 7% |

- **Fraudes reais**: 3 das 29 sinalizadas na sensibilidade 8 (12% em validação cruzada, contra
  10,5% dos autênticos), ou seja, sem separação. Das 29, 23 saíram do navegador, do "Imprimir em
  PDF" ou do Word, os mesmos geradores de quase metade dos PDFs autênticos: são documentos
  refeitos, que não guardam rastro de edição, e o que as distingue é o conteúdo, a cargo dos
  avaliadores textual e de metadados. Nas três sinalizadas o relatório aponta o trecho: a data em
  outra versão da fonte e em outro tamanho, nome e valores em uma segunda Arial, um aviso em
  Helvetica não embutida.
- **Recalibrar não resolve** (medido em 13/10/2026, com cinco páginas por documento): das 29
  fraudes, 15 não têm nenhum sinal medido, 4 delas por estarem em formato sem medida possível. O
  que não tem sinal nenhum limiar alcança. Três formas de calibrar foram comparadas em validação
  cruzada, e nas três a detecção acompanha o alarme falso: a atual (10,5% de autênticos e 11,1%
  de fraudes sinalizados na sensibilidade 8), a raridade medida entre documentos do mesmo número
  de páginas no lugar da correção por página (12,9% e 14,8%) e a mesma sem as pastas de
  documentos alterados na calibração (13,8% e 15,1%). A calibração não mudou.
- **Sinal que parecia forte e não é**: texto coberto e reescrito aparece em três fraudes, todas
  guias do FGTS, e também em guias do FGTS autênticas (12 documentos das pastas `gfip`). É como
  esse documento é gerado, não um rastro de fraude.
- **O que separa essas fraudes**, medido nos mesmos documentos, depende do tipo de documento e
  por isso não está nos sinais: virou as validações que comparam o arquivo com o esperado para o
  tipo (seção "Validações do arquivo"). Das 29 fraudes, 19 são de tipos cujos autênticos saem de
  poucos programas (CTPS, carta de permanência, guia do FGTS, eSocial, carteirinha). Dessas, 4
  saíram de um programa que nenhum autêntico do mesmo tipo usa (CTPS feitas no Word, cartas de
  permanência saídas do iLovePDF e de "Imprimir em PDF"), e outras 2 são guias do FGTS feitas
  no Word, que gerou 2 das 100 autênticas. Em comprovante de residência a comparação não serve:
  cada emissor usa um programa diferente. Na CTPS, 17 das 20 autênticas têm a assinatura digital
  da Dataprev, contra 1 das 5 fraudes.
- **Medidas da referência**: ELA, ruído, nitidez, tom do fundo e grade JPEG por bloco não
  reagiram a nenhuma adulteração sintética, e o ELA sinaliza qualquer JPEG que só foi regravado.
  É o motivo de não haver limiar que funcionasse; ficaram de fora.
- **Alarmes falsos concentrados**: na sensibilidade 8, 10 de 20 comprovantes de residência e 6 de
  20 eSocial de `docs/` são sinalizados. O formato não explica tudo: contas têm tabelas e códigos
  repetidos.
- **Poucas páginas autênticas em alguns formatos** (75 de digitalização, 37 de print em PDF): com
  n páginas a menor raridade possível é 1/(n+1), então nesses formatos nada é sinalizado abaixo
  da sensibilidade 4. Mais documentos autênticos resolvem.

#### Recalibrar

```
python -m subscricao.fraude.forense.calibrar PASTA_DE_AUTENTICOS --fraudes PASTA_DE_FRAUDES --medidas medidas.json
python -m subscricao.fraude.forense.calibrar --de-medidas medidas.json
```

O primeiro comando mede os documentos (cerca de 10 minutos para 850) e grava `calibracao.json`
com a tabela de alarme falso e detecção por sensibilidade; o segundo refaz a calibração a partir
das medidas gravadas. A coluna de adulterações sintéticas veio do estudo e não é refeita por esse
comando.

## Adicionar um documento

1. Na tela, aba "Tipos de documento e campos": crie o tipo com a descrição para a classificação e
   o nível de risco, preencha os campos e as instruções e salve. A partir daí o documento já é
   classificado, extraído e analisado quanto a fraude. Se todo documento autêntico desse tipo
   chega do mesmo jeito, preencha também o arquivo esperado.
2. Para validá-lo, crie `validacoes/<documento>_validate.py` com regras prontas e funções
   `@validacao`. Os campos usados precisam existir no catálogo; um teste e um aviso na tela
   apontam o que faltar.

## O que mudou em relação à referência

- **Ficha de cadastro**: é o `cartao_proposta` da referência. Deixou de ser um argumento fixo de
  toda validação e virou um documento que a validação declara quando precisa.
- **Validações com outros documentos**: na referência, `@required_docs('estatuto_social')` buscava
  o documento no MongoDB e o passava como argumento. Aqui o mesmo papel é do `campos` do
  `@validacao`, e os documentos vêm dos arquivos processados na mesma execução. As validações da
  referência que recebiam vários documentos e tratavam como `None` o que faltasse viram uma
  condição OU (seção "Um entre vários documentos").
- **Corpo das validações**: `tools.py` e `Distances.py` são cópias idênticas. Em `rg_validate.py` e
  `contrato_social_validate.py` só mudaram os nomes dos argumentos (`self.cartao_proposta` virou
  `ficha_cadastro`; `self.dados_extraidos` virou `rg` ou `contrato_social`). Os dataclasses saíram
  desses arquivos. `ValidateDocument.py` mantém a montagem do resultado e os códigos de erro.
- **Fim do grupo de fraude nas validações**: `validacao_ha_quadro_societario` e
  `validacao_ha_rodape_autenticacao_junta`, que na referência tinham `output='fraud'`, agora são
  validações de tipo `visual` como as outras. Não existe mais `fraud_validations`.
- **Prompts de fraude**: `subscricao/fraude/prompts.py` é cópia das seis prompts usadas pelo
  orquestrador B, em que só a lista de documentos de cada risco virou `{documentos_risco}`. As
  prompts enviadas são montadas em `prompts_poc.py` a partir dessa cópia; a seção "Prompts" lista
  o que mudou.
- **Decisão**: a pontuação e o status saem de `decisao.py`, pelas regras de cada nível de risco em
  `fraude.json`. Na referência a conta era feita pela LLM, com a matriz escrita na prompt.
- **Níveis de risco**: são quatro em vez de três. O baixo risco da referência, que nunca
  classifica um documento como suspeito, aqui se chama `NULO`. O `BAIXO` é novo e avalia o
  documento; os tipos que a referência trata como baixo risco estão nele.
- **Validações do arquivo**: não existem na referência. A assinatura digital, o programa gerador,
  o formato, as datas dos metadados e as marcas de geração por IA são conferidos por código, e as
  reprovadas entram na decisão como flags.
- **Tipos de documento**: 13 tipos do catálogo não existem na referência.
- **Resposta do orquestrador**: é estruturada (a API garante o formato), no lugar do JSON em texto
  livre. Os avaliadores auxiliares continuam respondendo em texto.
- **Metadados**: além das chaves da referência, vão `author` e `title`, que a prompt de metadados
  já avaliava, e as datas vão em formato legível. Para imagens o avaliador de metadados não roda.
- **Análise algorítmica**: o `visual_analysis.py` (limiares por tipo de documento, só para
  `gfip_novo`, `esocial`, `carta_permanencia` e `cartao_plano`) deu lugar ao avaliador de
  `forense/`, por formato de arquivo e com um único limiar.
- **Markdown**: vem do docling, não da prompt `doc2markdown` da referência. Com mais de uma
  página, cada uma começa com `--- PÁGINA N ---`, como lá. As convenções `[ILEGÍVEL]`,
  `[DUVIDOSO]`, `[VAZIO]` e `[ELEMENTO]` não existem, e as prompts não as citam mais.
- **Prompts de extração**: deixaram de ser um texto por documento com a lista de perguntas e
  passaram a ser montadas a partir do catálogo. O texto foi reaproveitado: as instruções de cada
  documento viraram `instrucoes` e cada pergunta virou a `descricao` de um campo, quase sempre
  literalmente. São novos: as descrições dos campos `confianca_*`, a de `cpfs` e a primeira linha
  das instruções textuais do contrato social. Saíram as regras sobre o formato da resposta
  (perguntas separadas por `//`, JSON com a pergunta como chave) e o mapeamento `llm_to_object`.
- **Detecção de assinaturas do Textract**: retirada (bloco `<assinaturas_textract>` e a instrução
  sobre a confiança da assinatura do OCR).
- **`cpfs`**: é uma lista de `{nome, cpf}` em vez de um objeto com o nome como chave, porque o
  formato de resposta garantido pela API não aceita chaves dinâmicas.
- **Nomes**: o que a referência chama de `information` e `signature` aqui é `textual` e `visual`.
- **Extração visual**: recebe o arquivo inteiro em uma única chamada, em vez das imagens das páginas
  em grupos de 5.

## Limitações conhecidas

- **Verificação de identificadores**: o cálculo dos dígitos da matrícula de certidão só pôde ser
  conferido com uma matrícula real. A consulta da cobrança Pix nunca devolveu uma cobrança viva
  (as guias de exemplo são de 2024 e a Caixa responde que não existem mais), então a comparação
  de valores só foi exercitada com respostas simuladas. O leitor de QR Code não lê todos os
  códigos de fotos e digitalizações, e o QR Code da CNH só é lido pelo serviço do Serpro. O
  contexto dos verificadores ainda não é preenchido pela tela: só as verificações que não
  dependem de informação de fora rodam por lá.
- **Avaliador forense**: não detecta documento refeito na origem, PDF reimpresso, adulteração
  impressa e digitalizada de novo, campo reescrito com ruído parecido com o do papel, nem edição
  em print de tela. Os números estão em "O que o estudo mediu".
- **Prompts de fraude sem medição**: com LLM real, a análise de fraude só rodou em documentos
  fictícios: uma carta de permanência com inconsistências plantadas, que apontou todas, e nove
  documentos gerados por código, em 13/10/2026 (seis deles estão em `../docs_ficticios_ia/`).
  Os seis de risco alto passaram duas vezes, e três deles uma terceira. O que tinha CPF, CNPJ e
  linha digitável com dígito verificador inválido saiu suspeito nas duas. A CTPS saiu suspeita em
  duas rodadas e autêntica em uma, porque o avaliador de metadados mudou de conclusão sobre o
  mesmo arquivo, e a carteirinha recebeu uma flag em uma rodada e nenhuma na outra: a resposta da
  LLM varia, e uma rodada não mede nada. Nessas rodadas a flag do arquivo fora do esperado ainda
  era moderada. O risco baixo e um tipo novo de risco médio rodaram uma
  vez (um cartão CNPJ com o dígito verificador certo, outro com ele errado, e um holerite) e
  saíram como as regras preveem: só o do dígito errado ficou suspeito. Isso mostra que o fluxo
  funciona, não que as prompts acertam: as mudanças nas prompts, a prompt do risco `BAIXO`, que
  agora vale para dez tipos de documento, e as regras de decisão ainda não foram medidas com
  documentos reais. O conjunto natural para isso são as 29 fraudes de `docs_fraude_QA/` e uma
  amostra de autênticos de `docs/`.
- **Geração de validações sem medição**: com LLM real, rodou uma vez, em um documento de regras
  fictício de seis regras para a CNH, e separou corretamente as quatro prontas das duas
  pendentes. Não foi testada com documentos de regras reais.
- **Tipos de documento sem validação**: dos 39 tipos do catálogo, só RG e contrato social têm
  validações. A extração dos outros 24 que vieram da referência só foi exercitada com LLM
  simulada (a do cartão CNPJ rodou uma vez com o modelo real, em um documento fictício), e a dos
  13 acrescentados só rodou para o holerite.
- **Validações do arquivo**: o programa gerador e as datas são metadados que quem gera o arquivo
  escolhe. A assinatura digital é conferida sem a cadeia de confiança, a validade e a revogação
  do certificado. As marcas de geração por IA não foram testadas com arquivos reais de gerador.
  O arquivo esperado só vem preenchido para CTPS, carta de permanência e GFD, e nesses tipos a
  reprovação basta para o documento sair suspeito: os limites estão na seção "Validações do
  arquivo".
- **Validações geradas**: regras que dependem de campos que o catálogo não extrai ficam como
  pendência; a tela não altera o catálogo.
- **Fatos conferidos por código**: só o dígito verificador de CPFs e CNPJs escritos com
  pontuação. Somas e totais dos documentos não são conferidos.
- **Origem do texto**: é decidida pelas páginas que o avaliador forense lê (as cinco primeiras).
- **Metadados**: são lidos com o pdfium. `encryption` vem sempre vazio.
- **Base de conhecimento**: a consulta à Knowledge Base do Bedrock não existe aqui. Em produção ela
  também está desligada (`KNOWLEDGE_BASE_ID` vazio).
- **Classificação de imagem do DataRobot**: a etapa `classificacao_imagem` da lambda de fraude
  ficou fora.
- **Raciocínio nos documentos de baixo risco da referência**: a referência desliga o raciocínio
  do modelo para eles, e a prompt deles é a do risco nulo daqui. O modelo padrão daqui não
  permite desligar; use `LLM_EFFORT` para reduzir.
- **Um documento por tipo**: se dois arquivos forem do mesmo tipo, cada um é validado com os
  próprios dados, mas os outros documentos enxergam só o primeiro.
- **Documentos alternativos**: a condição OU diz que um entre vários documentos basta, mas não
  escolhe qual usar quando a proposta tem mais de um do mesmo tipo: continua valendo o primeiro
  (item anterior).
- **Tela para uma pessoa**: o catálogo e a configuração de fraude são arquivos únicos, sem controle
  de edição simultânea nem histórico, e a tela não tem login. O modo desenvolvedor não é protegido
  por senha.
- **Tamanho do arquivo**: a API aceita PDFs de até 600 páginas e requisições de até 32 MB. Imagens
  acima de 3,75 MB ou em formato diferente de JPEG/PNG são recomprimidas em JPEG.
- **Parâmetros de amostragem**: `temperature`, `top_p` e `top_k` da referência não são enviados,
  porque os modelos Claude atuais rejeitam esses parâmetros.
- **Fotos rotacionadas**: o OCR do docling lê pior documentos fotografados de lado.
- **Validações de fraude por metadados e por similaridade** (`fraud_metadata`,
  `include_docs_same_type_from_proposal`) dependem do MongoDB e ficaram fora da POC.
