# Métricas de conversas — GHL + IA

Lê as conversas dos leads no GHL, classifica cada uma com a API da OpenAI (origem, segmento, porte,
dor, dúvida, desfecho, motivo da perda, objeção + resumo), salva no Postgres (Supabase) e gera um
dashboard que pode ser aberto dentro do GHL pelo menu lateral.

**Modo padrão: o GHL só é lido.** Gravar campos e tags nos contatos é opcional (`GRAVAR_NO_GHL=sim`).

```
GHL (conversas) ──► coletor.main ──► OpenAI (classificação presa à taxonomia)
                         │
                         └─► Postgres (Supabase) ──► coletor.dashboard ──► publicar/ (site)
```

## Organização

```
Matte/
├── coletor/                 código Python (rode sempre da pasta do projeto: python -m coletor.<script>)
│   ├── main.py              busca conversas, classifica e salva
│   ├── dashboard.py         monta o site em publicar/ com os dados do banco
│   ├── classificar.py       chamada à OpenAI (instruções + formato da resposta)
│   ├── ghl.py               cliente da API do GHL
│   ├── banco.py             Postgres / SQLite
│   ├── relatorio.py         métricas em texto + CSV (sem IA)
│   ├── sincronizar_campos.py  cria campos no GHL (só se GRAVAR_NO_GHL=sim)
│   └── config.py            lê o .env e a taxonomia
├── dashboard/               código do site (é aqui que se edita o visual)
│   ├── index.html           estrutura
│   ├── css/estilo.css       visual
│   └── js/app.js            gráficos, filtros e períodos
├── marca/                   logo e seta da Matte (PNG transparente)
├── publicar/                GERADO: o que vai para a hospedagem (não edite à mão)
├── taxonomia.json           categorias e opções que a IA pode escolher
├── .env / .env.example      acessos (o .env nunca vai para o git)
├── pyproject.toml           configuração do ruff (formatador do Python)
└── .prettierrc.json         configuração do Prettier (HTML, CSS, JS)
```

## Primeira vez

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
copy .env.example .env          # preencha GHL, DATABASE_URL e OpenAI
python -m coletor.banco         # testa a conexão com o banco e cria as tabelas
```

## Uso

```powershell
# Teste sem gravar nada: 50 conversas -> CSV em relatorios/
python -m coletor.main --dias 30 --limite 50 --seco

# Retroativo dos últimos 30 dias, salvando no banco
python -m coletor.main --dias 30

# Dia a dia: só o que mudou desde a última execução
python -m coletor.main

# Monta o site com os dados do banco (abra publicar/index.html no navegador)
python -m coletor.dashboard
python -m coletor.dashboard --demo   # dados de exemplo

# Métricas em texto + CSV
python -m coletor.relatorio --dias 30
```

Conversas sem mensagem nova desde a última análise são puladas. Quem não respondeu no período é
registrado sem IA (custo zero). Use `--forcar` para reanalisar tudo (por exemplo, depois de mudar a
taxonomia).

**Custo de referência (GPT-5 mini, 30 mensagens por conversa):** ~US$ 0,0017 por conversa analisada.
O mês de 12/10 a 12/11/2026 (12.267 conversas, 2.861 pela IA) custou US$ 5,28.

## Dashboard

- **Períodos:** atalhos Hoje · Ontem · 7 dias · 30 dias e, em "Mais períodos": esta semana, semana
  passada, este mês, mês passado, 60 dias, todo o histórico e **datas personalizadas**. O período
  escolhido fica lembrado no navegador.
- **Comparação:** cada indicador compara com o período anterior equivalente (ontem × anteontem,
  semana passada × semana retrasada, mês passado × mês anterior...), quando há dados para isso.
- Períodos curtos (menos de 7 dias) mostram o gráfico diário dos últimos 14 dias com o período em destaque.
- Filtros de segmento e origem; clicar numa barra ou fatia filtra tudo; cada gráfico tem botão **Tabela**.
- `publicar/dados.js` leva só as classificações e o dia de cada conversa: **nada de nome, telefone ou
  resumo**. Por isso pode ser hospedado.

### Editar o visual

Edite `dashboard/` (HTML, CSS, JS) e rode `python -m coletor.dashboard` para copiar para `publicar/`.
Com a extensão Prettier no VS Code, os arquivos são formatados ao salvar (`.vscode/settings.json`);
o Python é formatado pelo ruff (`python -m ruff format coletor/`).

### Fonte Quantify

A Quantify grátis é só para uso **não comercial** e a versão da Creative Fabrica não permite uso em sites.
Com uma licença web, coloque o arquivo (.woff2/.woff/.otf/.ttf) em `fontes/` e rode
`python -m coletor.dashboard`: ela passa a ser usada no lugar da Urbanist.

### Publicar e abrir dentro do GHL

1. Hospedar a pasta `publicar/` (Vercel com Root Directory = `publicar`, ou Cloudflare Pages).
   Atenção: o plano grátis (Hobby) da Vercel é só para uso não comercial.
2. No GHL: Configurações da agência > **Custom Menu Links** > novo link com a URL publicada, modo
   **iframe**, visível só na subconta da Matte. Não altera os dashboards que já existem.

## Banco (Supabase)

1. Projeto em supabase.com; em **Connect > Direct > Session pooler** copie a URI.
2. Cole em `DATABASE_URL` no `.env`, trocando `[YOUR-PASSWORD]` pela senha (caracteres especiais
   precisam estar codificados, ex.: `@` = `%40`, `#` = `%23`).
3. `python -m coletor.banco` deve mostrar `Conectado: Postgres (nuvem)`.

| Tabela      | Conteúdo                                                                             |
| ----------- | ------------------------------------------------------------------------------------ |
| `analises`  | Situação mais recente de cada conversa: IDs, nome do contato, classificação e resumo |
| `historico` | Toda análise feita, só acrescenta (evolução: "Em conversa" → "Reunião agendada")     |
| `execucoes` | Cada rodada do coletor (controla o modo incremental)                                 |

Não são salvos telefone, e-mail nem o texto das mensagens. As tabelas ficam bloqueadas para a API
pública do Supabase (RLS).

## O que o projeto altera no GHL

| Altera (só com `GRAVAR_NO_GHL=sim`)                      | Nunca altera                                                   |
| -------------------------------------------------------- | -------------------------------------------------------------- |
| Cria campos novos `IA - ...` (só se ainda não existirem) | Campos existentes, dashboards, pipelines, workflows, conversas |
| Preenche esses campos nos contatos                       | Nenhum outro campo do contato                                  |
| Adiciona/troca tags que começam com `ia-`                | Tags do time (o código bloqueia prefixo sem `ia-`)             |
