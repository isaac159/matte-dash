/* =========================================================
   Matte — Inteligência de Conversas
   Lógica do dashboard: filtros, períodos, gráficos e tabelas.
   Sem bibliotecas: SVG + CSS com animações leves.
   Os dados chegam em window.DADOS (arquivo dados.js, gerado pelo coletor).
   ========================================================= */

(() => {
  "use strict";

  const DADOS = window.DADOS;
  const CATS = DADOS.categorias;
  const DIA = 86400000;
  const NEUTRAS = ["Outro", "Não identificado", "Nenhuma"];
  const NAO_SE_APLICA = "Não se aplica";
  const NAO_RESPONDEU = "Não respondeu";
  const PEDIU_PARAR = "Pediu para parar";
  const CORES_ORIGEM = ["#d3135a", "#e4e4e7", "#55555f"];
  const ATALHOS = ["hoje", "ontem", "7d", "30d"];
  const CHAVE_MEMORIA = "matte-dashboard-periodo";
  const reduzir = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // registros compactos [dia, índice de cada categoria] -> objetos { d, segmento: "...", ... }
  const REG = DADOS.r.map((linha) => {
    const o = { d: linha[0] };
    CATS.forEach((c, i) => {
      o[c.chave] = c.opcoes[linha[i + 1]];
    });
    return o;
  });

  // dias contados no horário de Brasília, igual ao coletor
  const hoje = Math.floor((Date.now() + DADOS.fuso_ms) / DIA);
  const primeiroDia = REG.reduce((min, r) => Math.min(min, r.d), hoje);

  const estado = { periodo: { id: "30d" }, segmento: "", origem: "" };
  const modoTabela = {};

  // =========================================================
  // Utilitários
  // =========================================================

  function el(tag, cls, texto) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (texto != null) e.textContent = texto;
    return e;
  }

  const cat = (chave) => CATS.find((c) => c.chave === chave);
  const pct = (n, t) => (t ? Math.round((n / t) * 100) : 0);
  const fmt = (n) => Math.round(n).toLocaleString("pt-BR");
  const DESFECHO = cat("desfecho");
  const respondeu = (r) => r.motivo_perda !== NAO_RESPONDEU;
  const reuniao = (r) => !!DESFECHO && r.desfecho === DESFECHO.opcoes[0];
  const pediuParar = (r) => r.motivo_perda === PEDIU_PARAR;

  function contar(regs, chave) {
    const c = {};
    regs.forEach((r) => {
      c[r[chave]] = (c[r[chave]] || 0) + 1;
    });
    return c;
  }

  function contarAte(e, alvo, sufixo = "") {
    const de = Number(e.dataset.v || 0);
    e.dataset.v = alvo;
    if (reduzir || de === alvo) {
      e.textContent = fmt(alvo) + sufixo;
      return;
    }
    const t0 = performance.now();
    const passo = (t) => {
      const k = Math.min(1, Math.max(0, (t - t0) / 700));
      const ease = 1 - Math.pow(1 - k, 3);
      e.textContent = fmt(de + (alvo - de) * ease) + sufixo;
      if (k < 1) requestAnimationFrame(passo);
    };
    requestAnimationFrame(passo);
  }

  const animar = (fn) => requestAnimationFrame(() => requestAnimationFrame(fn));
  const animarLargura = (barra, alvo) => animar(() => (barra.style.width = alvo));

  // =========================================================
  // Datas e períodos
  // =========================================================

  // índice do dia -> Date cujos campos UTC são a data de Brasília
  const dataDoDia = (d) => new Date(d * DIA);
  const diaDaSemana = (d) => (dataDoDia(d).getUTCDay() + 6) % 7; // 0 = segunda
  const inicioDoMes = (d) => {
    const x = dataDoDia(d);
    return Math.floor(Date.UTC(x.getUTCFullYear(), x.getUTCMonth(), 1) / DIA);
  };
  const ddmm = (d) => {
    const x = dataDoDia(d);
    return `${String(x.getUTCDate()).padStart(2, "0")}/${String(x.getUTCMonth() + 1).padStart(2, "0")}`;
  };
  const faixaTexto = (de, ate) => (de === ate ? ddmm(de) : `${ddmm(de)} a ${ddmm(ate)}`);
  const diaDoInput = (valor) => {
    const [a, m, d] = valor.split("-").map(Number);
    return Math.floor(Date.UTC(a, m - 1, d) / DIA);
  };
  const inputDoDia = (d) => dataDoDia(d).toISOString().slice(0, 10);

  const PERIODOS = [
    { id: "hoje", rotulo: "Hoje", comparar: "dia anterior", faixa: () => [hoje, hoje] },
    { id: "ontem", rotulo: "Ontem", comparar: "dia anterior", faixa: () => [hoje - 1, hoje - 1] },
    {
      id: "semana",
      rotulo: "Esta semana",
      comparar: "mesmos dias da semana anterior",
      faixa: () => [hoje - diaDaSemana(hoje), hoje],
    },
    {
      id: "semana-passada",
      rotulo: "Semana passada",
      comparar: "semana anterior",
      faixa: () => {
        const ini = hoje - diaDaSemana(hoje) - 7;
        return [ini, ini + 6];
      },
    },
    { id: "7d", rotulo: "Últimos 7 dias", comparar: "7 dias anteriores", faixa: () => [hoje - 6, hoje] },
    {
      id: "mes",
      rotulo: "Este mês",
      comparar: "mesmos dias do mês anterior",
      faixa: () => [inicioDoMes(hoje), hoje],
      anterior: (de, ate) => {
        const ini = inicioDoMes(de - 1);
        return [ini, Math.min(ini + (ate - de), de - 1)];
      },
    },
    {
      id: "mes-passado",
      rotulo: "Mês passado",
      comparar: "mês anterior",
      faixa: () => {
        const fim = inicioDoMes(hoje) - 1;
        return [inicioDoMes(fim), fim];
      },
      anterior: (de) => [inicioDoMes(de - 1), de - 1],
    },
    { id: "30d", rotulo: "Últimos 30 dias", comparar: "30 dias anteriores", faixa: () => [hoje - 29, hoje] },
    { id: "60d", rotulo: "Últimos 60 dias", comparar: "60 dias anteriores", faixa: () => [hoje - 59, hoje] },
    { id: "tudo", rotulo: "Todo o histórico", comparar: null, faixa: () => [primeiroDia, hoje] },
  ];

  /** Intervalo do período escolhido e do período anterior usado na comparação. */
  function intervaloAtual() {
    const p = estado.periodo;
    let de;
    let ate;
    let rotulo;
    let comparar = "período anterior";
    let anterior = null;
    if (p.id === "personalizado") {
      [de, ate] = [p.de, p.ate];
      rotulo = "Personalizado";
    } else {
      const def = PERIODOS.find((x) => x.id === p.id) || PERIODOS.find((x) => x.id === "30d");
      [de, ate] = def.faixa();
      rotulo = def.rotulo;
      comparar = def.comparar;
      if (def.anterior) anterior = def.anterior(de, ate);
      if (!def.comparar) comparar = null;
    }
    if (comparar && !anterior) {
      const tam = ate - de + 1;
      anterior = [de - tam, de - 1];
    }
    // só compara se houver dados cobrindo o período anterior inteiro
    if (!comparar || !anterior || anterior[0] < primeiroDia) anterior = null;
    return { de, ate, rotulo, comparar, anterior };
  }

  // =========================================================
  // Tooltip (valor primeiro, rótulo depois) — hover e teclado
  // =========================================================

  const dica = document.getElementById("dica");

  function mostrarDica(x, y, titulo, linhas = []) {
    dica.textContent = "";
    dica.appendChild(el("b", null, titulo));
    linhas.forEach((l) => {
      const d = el("div", "l");
      if (l.cor) {
        const i = el("i");
        i.style.background = l.cor;
        d.appendChild(i);
      }
      d.appendChild(document.createTextNode(l.rotulo));
      if (l.valor != null) d.appendChild(el("strong", null, l.valor));
      dica.appendChild(d);
    });
    dica.style.display = "block";
    const w = dica.offsetWidth;
    const h = dica.offsetHeight;
    dica.style.left = `${Math.max(8, Math.min(x + 14, window.innerWidth - w - 8))}px`;
    dica.style.top = `${y - h - 12 < 8 ? y + 18 : y - h - 12}px`;
  }

  const esconderDica = () => (dica.style.display = "none");

  function ligarDica(alvo, titulo, linhas, rotuloAcessivel) {
    alvo.setAttribute("tabindex", "0");
    alvo.setAttribute("aria-label", rotuloAcessivel || titulo);
    alvo.addEventListener("pointermove", (e) => mostrarDica(e.clientX, e.clientY, titulo, linhas));
    alvo.addEventListener("pointerleave", esconderDica);
    alvo.addEventListener("focus", () => {
      const r = alvo.getBoundingClientRect();
      mostrarDica(r.left + r.width / 2, r.top, titulo, linhas);
    });
    alvo.addEventListener("blur", esconderDica);
  }

  function aoAtivar(alvo, fn) {
    alvo.addEventListener("click", fn);
    alvo.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fn();
      }
    });
  }

  // =========================================================
  // Cartões: alternância gráfico / tabela
  // =========================================================

  function tabela(cabecalhos, linhas) {
    const t = el("table", "dados");
    const thead = el("thead");
    const tr = el("tr");
    cabecalhos.forEach((c, i) => tr.appendChild(el("th", i ? "n" : null, c)));
    thead.appendChild(tr);
    t.appendChild(thead);
    const tbody = el("tbody");
    linhas.forEach((l) => {
      const r = el("tr");
      l.forEach((v, i) => r.appendChild(el("td", i ? "n num" : null, v)));
      tbody.appendChild(r);
    });
    t.appendChild(tbody);
    return t;
  }

  function preencher(id, vis) {
    const fig = document.getElementById(`c-${id}`);
    const corpo = fig.querySelector(".corpo");
    const btn = fig.querySelector("[data-tabela]");
    corpo.textContent = "";
    if (!vis) {
      corpo.appendChild(el("p", "vazio", "Sem conversas neste filtro."));
      if (btn) btn.hidden = true;
      return;
    }
    if (btn) {
      btn.hidden = false;
      btn.textContent = modoTabela[id] ? "Gráfico" : "Tabela";
      btn.setAttribute("aria-pressed", String(!!modoTabela[id]));
      btn.onclick = () => {
        modoTabela[id] = !modoTabela[id];
        render();
      };
    }
    corpo.appendChild(modoTabela[id] ? vis.tabela() : vis.grafico());
  }

  // =========================================================
  // Barras ranqueadas (1 cor; "Outro/Não identificado" em cinza no fim)
  // =========================================================

  function barras(regs, c, opcoes = {}) {
    regs = regs.filter((r) => r[c.chave] !== NAO_SE_APLICA);
    if (!regs.length) return null;
    const cont = contar(regs, c.chave);
    const total = regs.length;
    const itens = c.opcoes
      .filter((v) => v !== NAO_SE_APLICA)
      .map((v) => ({ v, n: cont[v] || 0, neutra: NEUTRAS.includes(v) }))
      .filter((i) => i.n > 0 || !i.neutra);
    if (!opcoes.ordemFixa) itens.sort((a, b) => a.neutra - b.neutra || b.n - a.n);
    const max = Math.max(...itens.map((i) => i.n), 1);
    return {
      grafico() {
        const box = el("div", "barras");
        itens.forEach((i) => {
          const classes = ["linha"];
          if (i.neutra) classes.push("neutra");
          if (opcoes.aoClicar) classes.push("clicavel");
          if (opcoes.selecionado === i.v) classes.push("selecionada");
          const l = el("div", classes.join(" "));
          l.appendChild(el("span", "nome", i.v));
          const pista = el("div", "pista");
          const b = el("div", "barra");
          pista.appendChild(b);
          l.appendChild(pista);
          const val = el("span", "val num");
          val.appendChild(el("b", null, `${pct(i.n, total)}%`));
          val.appendChild(document.createTextNode(` · ${fmt(i.n)}`));
          l.appendChild(val);
          animarLargura(b, i.n ? `${Math.max(1.5, (i.n / max) * 100)}%` : "0");
          ligarDica(
            l,
            `${pct(i.n, total)}%`,
            [{ rotulo: i.v, valor: `${fmt(i.n)} conversas` }],
            `${i.v}: ${pct(i.n, total)}%, ${fmt(i.n)} conversas`,
          );
          if (opcoes.aoClicar) aoAtivar(l, () => opcoes.aoClicar(i.v));
          box.appendChild(l);
        });
        return box;
      },
      tabela: () =>
        tabela(
          [c.titulo, "Conversas", "%"],
          itens.map((i) => [i.v, fmt(i.n), `${pct(i.n, total)}%`]),
        ),
    };
  }

  // =========================================================
  // Indicadores (KPIs)
  // =========================================================

  const ICONES = {
    // WhatsApp (balão + telefone)
    conversas:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.6a9.3 9.3 0 0 0-8 14.1L2.6 21.4l4.9-1.3A9.3 9.3 0 1 0 12 2.6z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/><path d="M8.7 7.4c.4-.1.7.1.8.4l.9 2.1c.1.3 0 .7-.2.9l-.7.7c.7 1.4 1.8 2.5 3.2 3.2l.7-.7c.2-.2.6-.3.9-.2l2.1.9c.3.1.5.5.4.8l-.3 1.3c-.1.5-.6.8-1.1.8-4.4-.2-8-3.8-8.2-8.2 0-.5.3-1 .8-1.1z" fill="currentColor"/></svg>',
    // seta curva (resposta)
    resposta:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="gSeta" x1="1" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#d3135a"/><stop offset="1" stop-color="#8f0c3c"/></linearGradient></defs><path d="M22.5 8.2C16.8 3.6 8.4 4.6 6.2 13.4" fill="none" stroke="url(#gSeta)" stroke-width="2.6" stroke-linecap="round"/><path d="M2.3 12.2l4.4 9 4.9-8.1z" fill="#8f0c3c"/></svg>',
    // calendário de mesa com espiral
    reuniao:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 6.5h15v14H5z"/><path d="M5 20.5l-2 1.6V8.2L5 6.5"/><path d="M7 9.2h11"/><path d="M7 12.4h11M7 15.4h11M7 18.2h11M10.6 12.4v5.8M14.3 12.4v5.8"/><path d="M7.6 4.6v3M10.3 4.6v3M13 4.6v3M15.7 4.6v3M18.4 4.6v3" stroke-width="1.8"/></svg>',
    // proibido
    parar:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M4.9 4.9l14.2 14.2"/></svg>',
  };

  const kpiEls = {};

  function kpi(id, rotulo, comBarra) {
    if (kpiEls[id]) return kpiEls[id];
    const k = el("div", "cartao kpi");
    const topo = el("div", "linha-topo");
    const ic = el("div", "icone");
    ic.innerHTML = ICONES[id]; // SVG fixo deste arquivo, sem dados externos
    topo.appendChild(ic);
    const delta = el("span", "delta");
    topo.appendChild(delta);
    k.appendChild(topo);
    k.appendChild(el("div", "rot", rotulo));
    const valor = el("div", "valor");
    k.appendChild(valor);
    const det = el("div", "det");
    k.appendChild(det);
    const extra = el("div");
    k.appendChild(extra);
    let barra = null;
    if (comBarra) {
      const bp = el("div", "barra-prog");
      barra = el("div");
      bp.appendChild(barra);
      extra.appendChild(bp);
    }
    document.getElementById("kpis").appendChild(k);
    kpiEls[id] = { delta, valor, det, extra, barra };
    return kpiEls[id];
  }

  function textoDelta(atual, anterior, comparar, ehTaxa) {
    if (anterior == null) return "";
    if (ehTaxa) {
      const dp = Math.round(atual - anterior);
      return `${dp >= 0 ? "▲" : "▼"} ${Math.abs(dp)} p.p. vs ${comparar}`;
    }
    if (!anterior) return "";
    const v = Math.round(((atual - anterior) / anterior) * 100);
    return `${v >= 0 ? "▲" : "▼"} ${Math.abs(v)}% vs ${comparar}`;
  }

  function definirDelta(k, texto) {
    k.delta.textContent = texto;
    k.delta.hidden = !texto;
  }

  function sparkline(serie) {
    const n = serie.length;
    const max = Math.max(...serie, 1);
    const w = 200;
    const h = 34;
    const d = serie
      .map((v, i) => `${i ? "L" : "M"}${((i / Math.max(1, n - 1)) * w).toFixed(1)} ${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`)
      .join(" ");
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("class", "spark");
    svg.setAttribute("aria-hidden", "true");
    const area = document.createElementNS(ns, "path");
    area.setAttribute("d", `${d} L${w} ${h} L0 ${h} Z`);
    area.setAttribute("fill", "rgba(211,19,90,0.12)");
    const linha = document.createElementNS(ns, "path");
    linha.setAttribute("d", d);
    linha.setAttribute("fill", "none");
    linha.setAttribute("stroke", "#d3135a");
    linha.setAttribute("stroke-width", "2");
    linha.setAttribute("vector-effect", "non-scaling-stroke");
    linha.setAttribute("stroke-linejoin", "round");
    svg.appendChild(area);
    svg.appendChild(linha);
    return svg;
  }

  function renderKpis(regs, ant, intervalo, serieDiaria) {
    const total = regs.length;
    const resp = regs.filter(respondeu).length;
    const reun = regs.filter(reuniao).length;
    const parar = regs.filter(pediuParar).length;
    const cmp = intervalo.comparar;
    const aTot = ant ? ant.length : null;
    const aResp = ant ? ant.filter(respondeu).length : null;
    const aReun = ant ? ant.filter(reuniao).length : null;
    const aParar = ant ? ant.filter(pediuParar).length : null;
    const quando = `${intervalo.rotulo.toLowerCase()} · ${faixaTexto(intervalo.de, intervalo.ate)}`;

    const k1 = kpi("conversas", "Conversas no período");
    contarAte(k1.valor, total);
    k1.det.textContent = quando;
    definirDelta(k1, textoDelta(total, aTot, cmp));
    k1.extra.textContent = "";
    if (serieDiaria.some((v) => v)) k1.extra.appendChild(sparkline(serieDiaria));

    const taxaResp = total ? (resp / total) * 100 : 0;
    const k2 = kpi("resposta", "Responderam", true);
    contarAte(k2.valor, Math.round(taxaResp), "%");
    k2.det.textContent = `${fmt(resp)} de ${fmt(total)} contatados`;
    definirDelta(k2, aTot ? textoDelta(taxaResp, (aResp / aTot) * 100, cmp, true) : "");
    animarLargura(k2.barra, `${taxaResp}%`);

    const taxaReun = resp ? (reun / resp) * 100 : 0;
    const k3 = kpi("reuniao", "Reuniões agendadas", true);
    contarAte(k3.valor, reun);
    k3.det.textContent = `${Math.round(taxaReun)}% de quem respondeu`;
    definirDelta(k3, textoDelta(reun, aReun, cmp));
    animarLargura(k3.barra, `${taxaReun}%`);

    const taxaParar = total ? (parar / total) * 100 : 0;
    const k4 = kpi("parar", "Pediram para parar", true);
    contarAte(k4.valor, Math.round(taxaParar), "%");
    k4.det.textContent = `${fmt(parar)} pedidos de remoção`;
    definirDelta(k4, aTot ? textoDelta(taxaParar, (aParar / aTot) * 100, cmp, true) : "");
    animarLargura(k4.barra, `${taxaParar}%`);
  }

  // =========================================================
  // Conversas por dia (área + linha + mira; períodos curtos ganham contexto)
  // =========================================================

  function serieDiaria(regs, primeiro, n) {
    const tot = new Array(n).fill(0);
    const res = new Array(n).fill(0);
    regs.forEach((r) => {
      const i = r.d - primeiro;
      if (i >= 0 && i < n) {
        tot[i]++;
        if (respondeu(r)) res[i]++;
      }
    });
    return { tot, res };
  }

  function visDias(regs, primeiro, n, destaque) {
    if (!regs.length) return null;
    const { tot, res } = serieDiaria(regs, primeiro, n);
    const maxV = Math.max(...tot, 1);
    let passo = Math.pow(10, Math.floor(Math.log10(maxV)));
    [1, 2, 2.5, 5, 10].some((m) => {
      if (m * passo * 4 >= maxV) {
        passo *= m;
        return true;
      }
      return false;
    });
    const teto = passo * Math.ceil(maxV / passo);
    const x = (i) => (n === 1 ? 50 : (i / (n - 1)) * 100);
    const y = (v) => 100 - (v / teto) * 100;

    return {
      grafico() {
        const frag = document.createDocumentFragment();
        const wrap = el("div", "area-wrap");
        const ey = el("div", "eixo-y");
        for (let v = 0; v <= teto + 0.0001; v += passo) {
          const g = el("div");
          g.style.top = `${y(v)}%`;
          ey.appendChild(g);
          const s = el("span", "num", fmt(v));
          s.style.top = `${y(v)}%`;
          ey.appendChild(s);
        }
        wrap.appendChild(ey);

        // faixa rosa marcando o período escolhido quando o gráfico mostra contexto
        if (destaque) {
          const meio = n > 1 ? 50 / (n - 1) : 50;
          const faixa = el("div", "faixa-periodo");
          const ini = Math.max(0, x(destaque[0] - primeiro) - meio);
          const fim = Math.min(100, x(destaque[1] - primeiro) + meio);
          faixa.style.left = `${ini}%`;
          faixa.style.width = `${fim - ini}%`;
          wrap.appendChild(faixa);
        }

        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 100 100");
        svg.setAttribute("preserveAspectRatio", "none");
        svg.setAttribute("aria-hidden", "true");
        const defs = document.createElementNS(ns, "defs");
        const grad = document.createElementNS(ns, "linearGradient");
        grad.setAttribute("id", "gRosa");
        grad.setAttribute("x1", "0");
        grad.setAttribute("y1", "0");
        grad.setAttribute("x2", "0");
        grad.setAttribute("y2", "1");
        [
          ["0", "0.35"],
          ["1", "0"],
        ].forEach(([offset, opacidade]) => {
          const st = document.createElementNS(ns, "stop");
          st.setAttribute("offset", offset);
          st.setAttribute("stop-color", "#d3135a");
          st.setAttribute("stop-opacity", opacidade);
          grad.appendChild(st);
        });
        defs.appendChild(grad);
        svg.appendChild(defs);

        const caminho = (serie) => serie.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(2)} ${y(v).toFixed(2)}`).join(" ");
        [
          { s: tot, cor: "#e4e4e7", fill: "rgba(228,228,231,0.06)" },
          { s: res, cor: "#d3135a", fill: "url(#gRosa)" },
        ].forEach((cfg) => {
          const a = document.createElementNS(ns, "path");
          a.setAttribute("d", `${caminho(cfg.s)} L${x(n - 1)} 100 L${x(0)} 100 Z`);
          a.setAttribute("fill", cfg.fill);
          a.setAttribute("class", "area-fill");
          a.style.opacity = reduzir ? "1" : "0";
          svg.appendChild(a);
          const l = document.createElementNS(ns, "path");
          l.setAttribute("d", caminho(cfg.s));
          l.setAttribute("fill", "none");
          l.setAttribute("stroke", cfg.cor);
          l.setAttribute("stroke-width", "2");
          l.setAttribute("vector-effect", "non-scaling-stroke");
          l.setAttribute("stroke-linejoin", "round");
          l.setAttribute("stroke-linecap", "round");
          l.setAttribute("pathLength", "1000");
          l.setAttribute("class", "linha-desenho");
          l.style.strokeDasharray = "1000";
          l.style.strokeDashoffset = reduzir ? "0" : "1000";
          svg.appendChild(l);
          animar(() => {
            a.style.opacity = "1";
            l.style.strokeDashoffset = "0";
          });
        });
        wrap.appendChild(svg);

        const mira = el("div", "mira");
        const p1 = el("div", "ponto");
        const p2 = el("div", "ponto");
        p1.style.background = "#e4e4e7";
        p2.style.background = "#d3135a";
        wrap.append(mira, p1, p2);

        const camada = el("div", "camada-hover");
        camada.tabIndex = 0;
        camada.setAttribute("aria-label", "Conversas por dia. Use as setas esquerda e direita para navegar pelos dias.");
        let atual = n - 1;
        const marcar = (i, cx, cy) => {
          atual = i;
          const px = `${x(i)}%`;
          mira.style.left = px;
          mira.style.display = "block";
          p1.style.left = px;
          p1.style.top = `${y(tot[i])}%`;
          p1.style.display = "block";
          p2.style.left = px;
          p2.style.top = `${y(res[i])}%`;
          p2.style.display = "block";
          mostrarDica(cx, cy, ddmm(primeiro + i), [
            { cor: "#e4e4e7", rotulo: "Conversas", valor: fmt(tot[i]) },
            { cor: "#d3135a", rotulo: "Responderam", valor: `${fmt(res[i])} (${pct(res[i], tot[i])}%)` },
          ]);
        };
        const limpar = () => {
          mira.style.display = p1.style.display = p2.style.display = "none";
          esconderDica();
        };
        const marcarPorTeclado = (i) => {
          const r = camada.getBoundingClientRect();
          marcar(i, r.left + (x(i) / 100) * r.width, r.top + (y(tot[i]) / 100) * r.height);
        };
        camada.addEventListener("pointermove", (e) => {
          const r = camada.getBoundingClientRect();
          const i = Math.round(((e.clientX - r.left) / r.width) * (n - 1));
          marcar(Math.max(0, Math.min(n - 1, i)), e.clientX, e.clientY);
        });
        camada.addEventListener("pointerleave", limpar);
        camada.addEventListener("blur", limpar);
        camada.addEventListener("keydown", (e) => {
          if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
          e.preventDefault();
          marcarPorTeclado(Math.max(0, Math.min(n - 1, atual + (e.key === "ArrowRight" ? 1 : -1))));
        });
        camada.addEventListener("focus", () => marcarPorTeclado(atual));
        wrap.appendChild(camada);
        frag.appendChild(wrap);

        const ex = el("div", "eixo-x");
        const cada = Math.max(1, Math.ceil(n / 7));
        for (let j = 0; j < n; j += cada) {
          const sp = el("span", "num", ddmm(primeiro + j));
          sp.style.left = `${x(j)}%`;
          ex.appendChild(sp);
        }
        frag.appendChild(ex);
        return frag;
      },
      tabela() {
        const linhas = [];
        for (let i = n - 1; i >= 0; i--) linhas.push([ddmm(primeiro + i), fmt(tot[i]), fmt(res[i])]);
        return tabela(["Dia", "Conversas", "Responderam"], linhas);
      },
    };
  }

  // =========================================================
  // Origem (rosca, até 3 partes)
  // =========================================================

  function visOrigem(regs) {
    const c = cat("origem");
    if (!c || !regs.length) return null;
    const cont = contar(regs, "origem");
    const total = regs.length;
    const itens = c.opcoes
      .map((v, i) => ({ v, n: cont[v] || 0, cor: CORES_ORIGEM[i] || "#55555f" }))
      .filter((i) => i.n);
    return {
      grafico() {
        const wrap = el("div", "rosca-wrap");
        const rosca = el("div", "rosca");
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 150 150");
        const r = 62;
        const circ = 2 * Math.PI * r;
        const gap = itens.length > 1 ? 2.5 : 0;
        let acc = 0;
        const fundo = document.createElementNS(ns, "circle");
        fundo.setAttribute("cx", "75");
        fundo.setAttribute("cy", "75");
        fundo.setAttribute("r", String(r));
        fundo.setAttribute("fill", "none");
        fundo.setAttribute("stroke", "rgba(255,255,255,0.05)");
        fundo.setAttribute("stroke-width", "18");
        svg.appendChild(fundo);
        itens.forEach((i) => {
          const tam = Math.max(0, (i.n / total) * circ - gap);
          const s = document.createElementNS(ns, "circle");
          s.setAttribute("cx", "75");
          s.setAttribute("cy", "75");
          s.setAttribute("r", String(r));
          s.setAttribute("class", "seg");
          s.setAttribute("stroke", i.cor);
          s.setAttribute("stroke-dashoffset", String(-acc));
          s.style.strokeDasharray = `${reduzir ? tam : 0} ${circ}`;
          acc += (i.n / total) * circ;
          ligarDica(s, `${pct(i.n, total)}%`, [{ cor: i.cor, rotulo: i.v, valor: fmt(i.n) }], `${i.v}: ${pct(i.n, total)}%`);
          aoAtivar(s, () => alternarFiltro("origem", i.v));
          svg.appendChild(s);
          animar(() => (s.style.strokeDasharray = `${tam} ${circ}`));
        });
        rosca.appendChild(svg);
        const centro = el("div", "centro");
        const cc = el("div");
        cc.appendChild(el("b", null, fmt(total)));
        cc.appendChild(el("small", null, "conversas"));
        centro.appendChild(cc);
        rosca.appendChild(centro);
        wrap.appendChild(rosca);

        const lista = el("div", "leg-lista");
        itens.forEach((i) => {
          const item = el("div", `leg-item${estado.origem === i.v ? " selecionada" : ""}`);
          const q = el("i");
          q.style.background = i.cor;
          item.appendChild(q);
          item.appendChild(el("span", null, i.v));
          item.appendChild(el("b", "num", `${pct(i.n, total)}%`));
          ligarDica(
            item,
            `${pct(i.n, total)}%`,
            [{ cor: i.cor, rotulo: i.v, valor: `${fmt(i.n)} conversas` }],
            `${i.v}: ${pct(i.n, total)}%. Clique para filtrar.`,
          );
          aoAtivar(item, () => alternarFiltro("origem", i.v));
          lista.appendChild(item);
        });
        wrap.appendChild(lista);
        return wrap;
      },
      tabela: () =>
        tabela(
          ["Origem", "Conversas", "%"],
          itens.map((i) => [i.v, fmt(i.n), `${pct(i.n, total)}%`]),
        ),
    };
  }

  // =========================================================
  // Taxa de reunião por segmento
  // =========================================================

  function visConversao(regs) {
    const seg = cat("segmento");
    if (!seg) return null;
    const linhas = seg.opcoes
      .map((v) => {
        const resp = regs.filter((r) => r.segmento === v && respondeu(r));
        const ok = resp.filter(reuniao).length;
        return { v, total: resp.length, ok, taxa: resp.length ? ok / resp.length : 0, neutra: NEUTRAS.includes(v) };
      })
      .filter((l) => l.total > 0);
    if (!linhas.length) return null;
    linhas.sort((a, b) => a.neutra - b.neutra || b.taxa - a.taxa);
    return {
      grafico() {
        const box = el("div", "barras");
        linhas.forEach((l) => {
          const classes = ["linha", "medidor", "clicavel"];
          if (l.neutra) classes.push("neutra");
          if (estado.segmento === l.v) classes.push("selecionada");
          const row = el("div", classes.join(" "));
          row.appendChild(el("span", "nome", l.v));
          const pista = el("div", "pista");
          const b = el("div", "barra");
          if (l.neutra) b.style.background = "var(--neutral)";
          pista.appendChild(b);
          row.appendChild(pista);
          const val = el("span", "val num");
          val.appendChild(el("b", null, `${Math.round(l.taxa * 100)}%`));
          val.appendChild(document.createTextNode(` · ${fmt(l.ok)}/${fmt(l.total)}`));
          row.appendChild(val);
          animarLargura(b, `${l.taxa * 100}%`);
          ligarDica(
            row,
            `${Math.round(l.taxa * 100)}% viraram reunião`,
            [{ rotulo: l.v, valor: `${fmt(l.ok)} de ${fmt(l.total)}` }],
            `${l.v}: ${Math.round(l.taxa * 100)}% viraram reunião, ${fmt(l.ok)} de ${fmt(l.total)} que responderam`,
          );
          aoAtivar(row, () => alternarFiltro("segmento", l.v));
          box.appendChild(row);
        });
        return box;
      },
      tabela: () =>
        tabela(
          ["Segmento", "Responderam", "Reuniões", "Taxa"],
          linhas.map((l) => [l.v, fmt(l.total), fmt(l.ok), `${Math.round(l.taxa * 100)}%`]),
        ),
    };
  }

  // =========================================================
  // Funil
  // =========================================================

  function visFunil(regs) {
    if (!regs.length) return null;
    const resp = regs.filter(respondeu);
    const engajadosValores = DESFECHO ? DESFECHO.opcoes.slice(0, 3) : [];
    const etapas = [
      { nome: "Contatados", sub: "conversas no período", n: regs.length },
      { nome: "Responderam", sub: "escreveram algo", n: resp.length },
      {
        nome: "Engajados",
        sub: "em conversa, proposta ou reunião",
        n: resp.filter((r) => engajadosValores.includes(r.desfecho)).length,
      },
      { nome: "Reunião agendada", sub: "diagnóstico ou apresentação", n: regs.filter(reuniao).length },
    ];
    return {
      grafico() {
        const box = el("div", "funil");
        etapas.forEach((e, i) => {
          const row = el("div", "etapa");
          const nome = el("div", "nome", e.nome);
          nome.appendChild(el("small", null, e.sub));
          row.appendChild(nome);
          const pista = el("div", "pista");
          const b = el("div", "barra");
          pista.appendChild(b);
          row.appendChild(pista);
          const val = el("div", "val num");
          val.appendChild(el("b", null, fmt(e.n)));
          val.appendChild(el("div", null, i ? `${pct(e.n, etapas[i - 1].n)}% da etapa anterior` : "100%"));
          row.appendChild(val);
          animarLargura(b, `${e.n ? Math.max(1, (e.n / Math.max(1, etapas[0].n)) * 100) : 0}%`);
          const linhasDica = [{ rotulo: "Do total", valor: `${pct(e.n, etapas[0].n)}%` }];
          if (i) linhasDica.push({ rotulo: "Da etapa anterior", valor: `${pct(e.n, etapas[i - 1].n)}%` });
          ligarDica(b, `${fmt(e.n)} · ${e.nome}`, linhasDica, `${e.nome}: ${fmt(e.n)}, ${pct(e.n, etapas[0].n)}% do total`);
          box.appendChild(row);
        });
        return box;
      },
      tabela: () =>
        tabela(
          ["Etapa", "Conversas", "% do total"],
          etapas.map((e) => [e.nome, fmt(e.n), `${pct(e.n, etapas[0].n)}%`]),
        ),
    };
  }

  // =========================================================
  // Tabela comparativa por segmento (ordenável, linhas expansíveis)
  // =========================================================

  let ordem = { col: "total", desc: true };
  const abertos = {};

  function renderTabelaSegmentos(regs) {
    const box = document.getElementById("tabela-segmentos");
    box.textContent = "";
    const seg = cat("segmento");
    if (!seg || !regs.length) {
      box.appendChild(el("p", "vazio", "Sem conversas neste filtro."));
      return;
    }
    const linhas = seg.opcoes
      .map((v) => {
        const rs = regs.filter((r) => r.segmento === v);
        const resp = rs.filter(respondeu);
        const reun = rs.filter(reuniao).length;
        const dores = contar(
          resp.filter((r) => !NEUTRAS.includes(r.dor_principal)),
          "dor_principal",
        );
        const topo = Object.keys(dores).sort((a, b) => dores[b] - dores[a])[0] || "—";
        return {
          v,
          regs: rs,
          total: rs.length,
          taxaResp: rs.length ? resp.length / rs.length : 0,
          reun,
          taxaReun: resp.length ? reun / resp.length : 0,
          parar: rs.length ? rs.filter(pediuParar).length / rs.length : 0,
          dor: topo,
        };
      })
      .filter((l) => l.total);
    linhas.sort((a, b) => {
      const na = NEUTRAS.includes(a.v);
      const nb = NEUTRAS.includes(b.v);
      if (na !== nb) return na ? 1 : -1; // "Outro" e "Não identificado" sempre no fim
      const d = a[ordem.col] > b[ordem.col] ? 1 : a[ordem.col] < b[ordem.col] ? -1 : 0;
      return ordem.desc ? -d : d;
    });

    const cols = [
      ["v", "Segmento"],
      ["total", "Conversas"],
      ["taxaResp", "Responderam"],
      ["reun", "Reuniões"],
      ["taxaReun", "Taxa de reunião"],
      ["parar", "Pediram p/ parar"],
      ["dor", "Dor mais citada"],
      [null, ""],
    ];
    const t = el("table");
    const thead = el("thead");
    const tr = el("tr");
    cols.forEach(([col, titulo]) => {
      const h = el("th", col && col !== "v" && col !== "dor" ? "n" : null);
      if (col) {
        const b = el("button", null, titulo + (ordem.col === col ? (ordem.desc ? " ↓" : " ↑") : ""));
        b.type = "button";
        if (ordem.col === col) b.setAttribute("aria-sort", ordem.desc ? "descending" : "ascending");
        b.addEventListener("click", () => {
          ordem = { col, desc: ordem.col === col ? !ordem.desc : true };
          renderTabelaSegmentos(regs);
        });
        h.appendChild(b);
      }
      tr.appendChild(h);
    });
    thead.appendChild(tr);
    t.appendChild(thead);

    const taxa = (v) => {
      const s = el("span", "pill-taxa");
      const i = el("i");
      const b = el("b");
      b.style.width = `${Math.round(v * 100)}%`;
      i.appendChild(b);
      s.appendChild(document.createTextNode(`${Math.round(v * 100)}%`));
      s.appendChild(i);
      return s;
    };

    const tbody = el("tbody");
    linhas.forEach((l) => {
      const row = el("tr", `seg-linha${abertos[l.v] ? " aberta" : ""}`);
      row.tabIndex = 0;
      row.setAttribute("aria-expanded", String(!!abertos[l.v]));
      row.appendChild(el("td", null, l.v));
      row.appendChild(el("td", "n num", fmt(l.total)));
      const c3 = el("td", "n num");
      c3.appendChild(taxa(l.taxaResp));
      row.appendChild(c3);
      row.appendChild(el("td", "n num", fmt(l.reun)));
      const c5 = el("td", "n num");
      c5.appendChild(taxa(l.taxaReun));
      row.appendChild(c5);
      row.appendChild(el("td", "n num", `${Math.round(l.parar * 100)}%`));
      row.appendChild(el("td", null, l.dor));
      const cs = el("td", "n");
      cs.appendChild(el("span", "seta", "▾"));
      row.appendChild(cs);
      aoAtivar(row, () => {
        abertos[l.v] = !abertos[l.v];
        renderTabelaSegmentos(regs);
      });
      tbody.appendChild(row);

      if (abertos[l.v]) {
        const det = el("tr", "detalhe");
        const td = el("td");
        td.colSpan = cols.length;
        const grade = el("div", "detalhe-grade");
        const respRegs = l.regs.filter(respondeu);
        [
          ["motivo_perda", "Por que não avançou", l.regs],
          ["duvida_principal", "Dúvida principal", respRegs],
          ["porte", "Porte", respRegs],
        ].forEach(([chave, titulo, base]) => {
          const c = cat(chave);
          if (!c) return;
          const mini = el("div", "mini");
          mini.appendChild(el("h3", null, titulo));
          const vis = barras(base, c);
          mini.appendChild(vis ? vis.grafico() : el("p", "vazio", "Sem dados"));
          grade.appendChild(mini);
        });
        td.appendChild(grade);
        det.appendChild(td);
        tbody.appendChild(det);
      }
    });
    t.appendChild(tbody);
    box.appendChild(t);
  }

  // =========================================================
  // Filtros (segmento, origem) e etiquetas
  // =========================================================

  function alternarFiltro(chave, valor) {
    estado[chave] = estado[chave] === valor ? "" : valor;
    document.getElementById(`f-${chave}`).value = estado[chave];
    render();
  }

  function renderChips() {
    const box = document.getElementById("chips");
    box.textContent = "";
    [
      ["segmento", "Segmento"],
      ["origem", "Origem"],
    ].forEach(([chave, rotulo]) => {
      if (!estado[chave]) return;
      const chip = el("button", "chip");
      chip.type = "button";
      chip.appendChild(el("b", null, `${rotulo}:`));
      chip.appendChild(document.createTextNode(estado[chave]));
      chip.appendChild(el("span", null, "✕"));
      chip.setAttribute("aria-label", `Remover filtro ${rotulo}: ${estado[chave]}`);
      chip.addEventListener("click", () => alternarFiltro(chave, estado[chave]));
      box.appendChild(chip);
    });
  }

  const passaFiltros = (r) =>
    (!estado.segmento || r.segmento === estado.segmento) && (!estado.origem || r.origem === estado.origem);
  const filtrar = (de, ate) => REG.filter((r) => r.d >= de && r.d <= ate && passaFiltros(r));

  // =========================================================
  // Seletor de período
  // =========================================================

  const botaoPeriodos = document.getElementById("abrir-periodos");
  const painelPeriodos = document.getElementById("painel-periodos");

  function guardarPeriodo() {
    try {
      localStorage.setItem(CHAVE_MEMORIA, JSON.stringify(estado.periodo));
    } catch (e) {
      /* navegador bloqueou o armazenamento: segue sem lembrar */
    }
  }

  function lembrarPeriodo() {
    try {
      const salvo = JSON.parse(localStorage.getItem(CHAVE_MEMORIA) || "null");
      if (salvo && (salvo.id === "personalizado" ? salvo.de <= salvo.ate : PERIODOS.some((p) => p.id === salvo.id))) {
        estado.periodo = salvo;
      }
    } catch (e) {
      /* sem memória disponível */
    }
  }

  function escolherPeriodo(periodo) {
    estado.periodo = periodo;
    guardarPeriodo();
    fecharPainel();
    render();
  }

  function abrirPainel() {
    renderListaPeriodos();
    const { de, ate } = intervaloAtual();
    const inDe = document.getElementById("data-de");
    const inAte = document.getElementById("data-ate");
    [inDe, inAte].forEach((i) => {
      i.min = inputDoDia(primeiroDia);
      i.max = inputDoDia(hoje);
    });
    inDe.value = inputDoDia(Math.max(de, primeiroDia));
    inAte.value = inputDoDia(ate);
    painelPeriodos.hidden = false;
    botaoPeriodos.setAttribute("aria-expanded", "true");
    const marcado = painelPeriodos.querySelector('[aria-checked="true"]') || painelPeriodos.querySelector(".opcao");
    if (marcado) marcado.focus();
  }

  function fecharPainel() {
    painelPeriodos.hidden = true;
    botaoPeriodos.setAttribute("aria-expanded", "false");
  }

  function renderListaPeriodos() {
    const lista = document.getElementById("lista-periodos");
    lista.textContent = "";
    PERIODOS.forEach((p) => {
      const [de, ate] = p.faixa();
      const b = el("button", "opcao");
      b.type = "button";
      b.setAttribute("role", "menuitemradio");
      b.setAttribute("aria-checked", String(estado.periodo.id === p.id));
      b.appendChild(el("span", null, p.rotulo));
      b.appendChild(el("small", null, faixaTexto(Math.max(de, primeiroDia), ate)));
      b.addEventListener("click", () => escolherPeriodo({ id: p.id }));
      lista.appendChild(b);
    });
  }

  function atualizarControlesPeriodo(intervalo) {
    document.querySelectorAll("#atalhos-periodo button").forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset.periodo === estado.periodo.id));
    });
    const foraDosAtalhos = !ATALHOS.includes(estado.periodo.id);
    botaoPeriodos.classList.toggle("ativo", foraDosAtalhos);
    botaoPeriodos.textContent = foraDosAtalhos
      ? estado.periodo.id === "personalizado"
        ? faixaTexto(intervalo.de, intervalo.ate)
        : intervalo.rotulo
      : "Mais períodos";

    const desc = document.getElementById("periodo-desc");
    desc.textContent = "Mostrando ";
    desc.appendChild(el("b", null, intervalo.rotulo));
    let texto = ` · ${faixaTexto(intervalo.de, intervalo.ate)}`;
    if (intervalo.anterior) texto += ` · comparado com ${faixaTexto(intervalo.anterior[0], intervalo.anterior[1])}`;
    if (intervalo.de < primeiroDia) texto += ` · dados disponíveis a partir de ${ddmm(primeiroDia)}`;
    desc.appendChild(document.createTextNode(texto));
  }

  // =========================================================
  // Render geral
  // =========================================================

  function render() {
    esconderDica();
    const intervalo = intervaloAtual();
    const { de, ate } = intervalo;
    const regs = filtrar(de, ate);
    const ant = intervalo.anterior ? filtrar(intervalo.anterior[0], intervalo.anterior[1]) : null;

    // gráfico diário: períodos curtos mostram os 14 dias até o fim do período, com destaque
    const curto = ate - de + 1 < 7;
    const iniGrafico = curto ? Math.max(primeiroDia, ate - 13) : Math.max(de, primeiroDia);
    const nGrafico = Math.max(1, ate - iniGrafico + 1);
    const regsGrafico = curto ? filtrar(iniGrafico, ate) : regs;
    const serie = serieDiaria(regsGrafico, iniGrafico, nGrafico).tot;

    atualizarControlesPeriodo(intervalo);
    renderChips();
    renderKpis(regs, ant, intervalo, serie);

    document.getElementById("sub-dias").textContent = curto
      ? `Últimos ${nGrafico} dias, com o período escolhido em destaque`
      : "Contatados × leads que responderam";
    const legendaFaixa = document.getElementById("legenda-faixa");
    if (curto && !legendaFaixa) {
      const s = el("span");
      s.id = "legenda-faixa";
      s.appendChild(el("i", "faixa"));
      s.appendChild(document.createTextNode("Período escolhido"));
      document.getElementById("legenda-dias").appendChild(s);
    } else if (!curto && legendaFaixa) {
      legendaFaixa.remove();
    }
    preencher("dias", visDias(regsGrafico, iniGrafico, nGrafico, curto ? [de, ate] : null));
    preencher("origem", visOrigem(regs));

    // quem não respondeu quase nunca tem segmento: mostra só os identificados
    const seg = cat("segmento");
    const comSegmento = regs.filter((r) => r.segmento !== "Não identificado");
    document.getElementById("sub-segmento").textContent =
      `${fmt(comSegmento.length)} com segmento identificado · ` +
      `${fmt(regs.length - comSegmento.length)} sem segmento (a maioria não respondeu)`;
    preencher(
      "segmento",
      seg && comSegmento.length
        ? barras(comSegmento, seg, {
            aoClicar: (v) => alternarFiltro("segmento", v),
            selecionado: estado.segmento,
          })
        : null,
    );
    preencher("conversao", visConversao(regs));
    preencher("funil", visFunil(regs));

    const mp = cat("motivo_perda");
    const perdidos = regs.filter((r) => r.motivo_perda !== NAO_SE_APLICA).length;
    document.getElementById("sub-motivo").textContent = `${fmt(perdidos)} conversas sem resposta ou perdidas`;
    preencher("motivo_perda", mp ? barras(regs, mp) : null);

    // perfil: só entre quem respondeu (quem não respondeu não tem o que analisar)
    const resp = regs.filter(respondeu);
    const gp = document.getElementById("grade-perfil");
    ["dor_principal", "duvida_principal", "objecao", "porte"].forEach((chave) => {
      const c = cat(chave);
      if (!c) return;
      let fig = document.getElementById(`c-${chave}`);
      if (!fig) {
        fig = el("figure", "cartao");
        fig.id = `c-${chave}`;
        const cab = el("div", "cab");
        const t = el("div");
        t.appendChild(el("h2", null, c.titulo));
        t.appendChild(el("p", "sub-perfil"));
        cab.appendChild(t);
        const b = el("button", "btn", "Tabela");
        b.type = "button";
        b.dataset.tabela = chave;
        cab.appendChild(b);
        fig.appendChild(cab);
        fig.appendChild(el("div", "corpo"));
        gp.appendChild(fig);
      }
      fig.querySelector(".sub-perfil").textContent = `${fmt(resp.length)} leads que responderam`;
      preencher(chave, resp.length ? barras(resp, c, { ordemFixa: (DADOS.ordem_fixa || []).includes(chave) }) : null);
    });

    renderTabelaSegmentos(regs);
  }

  // =========================================================
  // Inicialização
  // =========================================================

  document.querySelectorAll("#atalhos-periodo button").forEach((b) => {
    b.addEventListener("click", () => escolherPeriodo({ id: b.dataset.periodo }));
  });

  botaoPeriodos.addEventListener("click", () => (painelPeriodos.hidden ? abrirPainel() : fecharPainel()));
  document.addEventListener("click", (e) => {
    if (!painelPeriodos.hidden && !e.target.closest(".periodos")) fecharPainel();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !painelPeriodos.hidden) {
      fecharPainel();
      botaoPeriodos.focus();
    }
  });
  document.getElementById("form-personalizado").addEventListener("submit", (e) => {
    e.preventDefault();
    let de = diaDoInput(document.getElementById("data-de").value);
    let ate = diaDoInput(document.getElementById("data-ate").value);
    if (de > ate) [de, ate] = [ate, de];
    escolherPeriodo({ id: "personalizado", de, ate });
  });

  [
    ["segmento", "Todos os segmentos"],
    ["origem", "Todas as origens"],
  ].forEach(([chave, rotuloTodos]) => {
    const sel = document.getElementById(`f-${chave}`);
    const c = cat(chave);
    if (!c) {
      sel.parentNode.hidden = true;
      return;
    }
    sel.appendChild(new Option(rotuloTodos, ""));
    c.opcoes.forEach((v) => sel.appendChild(new Option(v, v)));
    sel.addEventListener("change", () => {
      estado[chave] = sel.value;
      render();
    });
  });

  // menu lateral: destaca a seção visível
  const links = [...document.querySelectorAll("nav.lateral a")];
  if ("IntersectionObserver" in window) {
    const obs = new IntersectionObserver(
      (entradas) => {
        entradas.forEach((e) => {
          if (!e.isIntersecting) return;
          links.forEach((a) => a.classList.toggle("ativo", a.getAttribute("href") === `#${e.target.id}`));
        });
      },
      { rootMargin: "-20% 0px -70% 0px" },
    );
    links.forEach((a) => {
      const alvo = document.querySelector(a.getAttribute("href"));
      if (alvo) obs.observe(alvo);
    });
  }

  document.getElementById("atualizado").textContent = `Atualizado em ${DADOS.gerado_em}`;
  document.getElementById("atualizado-lateral").textContent = DADOS.gerado_em;
  window.addEventListener("scroll", esconderDica, { passive: true });

  lembrarPeriodo();
  render();
})();
