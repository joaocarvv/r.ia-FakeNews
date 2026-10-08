"""Área de pesquisa e leitura de artigos científicos."""

from __future__ import annotations

from html import escape

from flask import Flask, Response


WEB_UI_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>artfact — Evidências em saúde</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #17221d;
      --muted: #5d6a64;
      --paper: #f6f3eb;
      --surface: #fffdf8;
      --line: #d8ddd7;
      --brand: #145a45;
      --brand-dark: #0e4032;
      --accent: #e7a84b;
      --danger: #9b3d31;
      --shadow: 0 18px 55px rgba(30, 52, 43, .11);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      background:
        radial-gradient(circle at 8% 6%, rgba(231, 168, 75, .20), transparent 25rem),
        linear-gradient(145deg, #f4f0e5 0%, #f7f8f3 55%, #edf3ee 100%);
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.55;
    }
    .shell { width: min(1080px, calc(100% - 32px)); margin: 0 auto; padding: 34px 0 64px; }
    header { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; margin-bottom: 24px; }
    .eyebrow { color: var(--brand); font-size: .78rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
    h1 { margin: 6px 0 4px; font-family: Georgia, 'Times New Roman', serif; font-size: clamp(2.2rem, 6vw, 4.4rem); line-height: .96; letter-spacing: -.045em; }
    .subtitle { margin: 12px 0 0; max-width: 690px; color: var(--muted); font-size: 1.06rem; }
    .mode {
      flex: 0 0 auto; max-width: 310px; padding: 12px 14px; border: 1px solid #d69a43;
      border-radius: 12px; background: #fff5df; color: #684313; font-size: .82rem; font-weight: 700;
    }
    .panel { border: 1px solid rgba(20, 90, 69, .18); border-radius: 20px; background: rgba(255, 253, 248, .94); box-shadow: var(--shadow); }
    .form-panel { padding: clamp(20px, 4vw, 36px); }
    label { display: block; margin-bottom: 8px; font-weight: 750; }
    textarea, input, select {
      width: 100%; border: 1px solid #bfc9c1; border-radius: 12px; background: #fff;
      padding: 14px 15px; color: var(--ink); font: inherit; outline: none;
    }
    textarea { min-height: 118px; resize: vertical; }
    textarea:focus, input:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(20, 90, 69, .12); }
    .field + .field { margin-top: 18px; }
    .hint { margin: 6px 0 0; color: var(--muted); font-size: .83rem; }
    .actions { display: flex; align-items: center; gap: 16px; margin-top: 22px; flex-wrap: wrap; }
    button {
      border: 0; border-radius: 999px; padding: 13px 22px; background: var(--brand); color: white;
      font: inherit; font-weight: 800; cursor: pointer; transition: transform .15s ease, background .15s ease;
    }
    button:hover { background: var(--brand-dark); transform: translateY(-1px); }
    button:disabled { opacity: .55; cursor: wait; transform: none; }
    .safety { color: var(--muted); font-size: .83rem; max-width: 560px; }
    #status { display: none; margin-top: 22px; padding: 16px; border-radius: 13px; background: #eef5f0; }
    .status-row { display: flex; justify-content: space-between; gap: 12px; font-size: .9rem; font-weight: 700; }
    .progress { height: 8px; margin-top: 10px; overflow: hidden; border-radius: 99px; background: #dbe5df; }
    .progress > div { height: 100%; width: 0; background: var(--brand); transition: width .25s ease; }
    #error { display: none; margin-top: 20px; padding: 15px 17px; border: 1px solid #e2b3ad; border-radius: 12px; background: #fff0ee; color: var(--danger); }
    #result { display: none; margin-top: 28px; }
    #whole-article-report { display: none; margin-top: 28px; }
    #claim-review { display: none; margin-top: 28px; padding: clamp(22px, 4vw, 34px); }
    .review-intro { color: var(--muted); max-width: 760px; }
    .review-list { display: grid; gap: 14px; margin: 20px 0; }
    .review-claim { display: grid; grid-template-columns: auto 1fr; gap: 13px; align-items: start; padding: 18px; border: 1px solid var(--line); border-radius: 14px; background: #fbfcf9; }
    .review-claim input[type="checkbox"] { width: 20px; height: 20px; margin-top: 12px; accent-color: var(--brand); }
    .review-claim textarea { min-height: 88px; }
    .review-source { margin-top: 8px; color: var(--muted); font-size: .8rem; }
    .result-grid { display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(260px, .6fr); gap: 20px; }
    .result-card { padding: 24px; }
    .kicker { color: var(--brand); font-size: .75rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase; }
    h2 { margin: 7px 0 10px; font-family: Georgia, 'Times New Roman', serif; font-size: 2rem; line-height: 1.08; }
    h3 { margin: 0 0 14px; font-size: 1.05rem; }
    .indicator-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin: 0 0 20px; }
    .indicator-card { padding: 19px; }
    .indicator-card h3 { margin: 7px 0 8px; }
    .indicator-card p { margin: 0; color: var(--muted); font-size: .87rem; }
    .indicator-note { grid-column: 1 / -1; margin: -4px 2px 0; color: var(--muted); font-size: .8rem; }
    .structured-search { margin: 0 0 20px; padding: 22px 24px; }
    .structured-search-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
    .structured-search-card { padding: 15px; border: 1px solid var(--line); border-radius: 12px; background: #fbfcf9; }
    .structured-search-card h4 { margin: 0 0 8px; color: var(--brand-dark); }
    .structured-search-card p { margin: 5px 0; }
    .structured-search-record { padding: 9px 0; border-top: 1px solid var(--line); font-size: .84rem; }
    .structured-search-record:first-child { border-top: 0; padding-top: 0; }
    .structured-search-empty { color: var(--muted); font-size: .84rem; }
    .stack { display: grid; gap: 16px; margin-top: 20px; }
    .alert-list { display: grid; gap: 10px; padding: 0; list-style: none; }
    .alert-item { padding: 12px 14px; border-left: 4px solid var(--accent); border-radius: 8px; background: #fff8e9; }
    .alert-item[data-severity="CRITICAL"] { border-color: var(--danger); background: #fff0ee; }
    .alert-item strong { display: block; }
    .article-meta { color: var(--muted); font-size: .82rem; }
    .evidence { margin-top: 13px; padding-left: 13px; border-left: 3px solid var(--accent); }
    .evidence p { margin: 4px 0; }
    .badge { display: inline-block; padding: 3px 8px; border-radius: 999px; background: #e7f0eb; color: var(--brand-dark); font-size: .72rem; font-weight: 800; }
    .summary-box { margin-top: 18px; padding: 16px; border-radius: 13px; background: #eef5f0; }
    .summary-box strong { display: block; margin-bottom: 5px; }
    .claim-navigation { margin-bottom: 20px; padding: 20px 24px; }
    .claim-navigation p { margin: -6px 0 14px; color: var(--muted); font-size: .88rem; }
    .claim-tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .claim-tab {
      width: 100%; min-height: 154px; border: 1px solid var(--line); border-radius: 14px; padding: 14px;
      background: #fbfcf9; color: var(--ink); font-weight: 650; text-align: left;
      display: flex; flex-direction: column; align-items: stretch; gap: 8px;
    }
    .claim-tab:hover { border-color: var(--brand); background: #eef5f0; color: var(--brand-dark); }
    .claim-tab[aria-selected="true"] { border-color: var(--brand); background: var(--brand); color: white; }
    .claim-number { font-size: .7rem; font-weight: 850; letter-spacing: .09em; text-transform: uppercase; opacity: .78; }
    .claim-text { display: block; line-height: 1.35; }
    .claim-outcome { margin-top: auto; font-size: .78rem; font-weight: 750; }
    .claim-metrics { font-size: .72rem; opacity: .82; }
    .crossing { margin-top: 20px; padding: 24px; }
    .crossing-flow { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 16px 0; }
    .crossing-step { padding: 13px; border: 1px solid var(--line); border-radius: 12px; background: #fbfcf9; }
    .crossing-step strong { display: block; font-size: 1.35rem; color: var(--brand); }
    .crossing-step span { color: var(--muted); font-size: .78rem; }
    .chip-list { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 9px; }
    .chip { padding: 4px 9px; border-radius: 999px; background: #e7f0eb; color: var(--brand-dark); font-size: .74rem; font-weight: 700; }
    .reason { margin: 10px 0 0; color: #304039; font-size: .9rem; }
    .missing-quote { margin: 12px 0; padding: 10px 12px; border-radius: 9px; background: #fff5df; color: #684313; font-size: .82rem; }
    .document-report { margin-bottom: 20px; padding: clamp(22px, 4vw, 34px); }
    .coverage-banner { margin: 14px 0 20px; padding: 13px 15px; border-radius: 12px; background: #eef5f0; color: var(--brand-dark); font-weight: 750; }
    .coverage-banner[data-complete="false"] { background: #fff5df; color: #684313; }
    .study-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }
    .study-field { padding: 13px; border: 1px solid var(--line); border-radius: 11px; background: #fbfcf9; }
    .study-field strong { display: block; color: var(--brand); font-size: .73rem; letter-spacing: .06em; text-transform: uppercase; }
    .report-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 18px; }
    .report-subpanel { padding: 18px; border: 1px solid var(--line); border-radius: 14px; background: #fbfcf9; }
    .report-finding { padding: 16px 0; border-top: 1px solid var(--line); }
    .report-finding:first-child { border-top: 0; padding-top: 0; }
    .citation { margin-top: 9px; padding: 10px 12px; border-left: 3px solid var(--brand); background: #eef5f0; font-size: .83rem; }
    .citation[data-verified="false"] { border-left-color: var(--accent); background: #fff5df; }
    .finding { padding: 20px; border: 1px solid var(--line); border-radius: 12px; background: #fbfcf9; }
    .finding[data-relation="CONTRADICTS"] { border-left: 5px solid var(--danger); }
    .finding[data-relation="SUPPORTS"] { border-left: 5px solid var(--brand); }
    .finding[data-relation="NEUTRAL"], .finding[data-relation="UNCERTAIN"] { border-left: 5px solid var(--accent); }
    .finding blockquote { margin: 12px 0; padding-left: 14px; border-left: 3px solid var(--line); color: #304039; }
    details { margin-top: 20px; }
    summary { cursor: pointer; color: var(--brand); font-weight: 750; }
    ul { margin: 0; padding-left: 20px; }
    li + li { margin-top: 8px; }
    a { color: var(--brand); overflow-wrap: anywhere; }
    footer { margin-top: 28px; color: var(--muted); font-size: .79rem; text-align: center; }
    .claim-card { display: grid; gap: 10px; padding: 18px; border: 1px solid var(--line); border-radius: 14px; background: #fbfcf9; }
    .claim-card[data-checked="true"] { border-color: var(--brand); box-shadow: 0 0 0 2px rgba(20, 90, 69, .12); }
    .claim-card-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
    .claim-card-head label { display: flex; align-items: center; gap: 9px; margin: 0; }
    .claim-card-head input[type="checkbox"] { width: 20px; height: 20px; accent-color: var(--brand); }
    .claim-card textarea { min-height: 84px; }
    .badge[data-level="HIGH"] { background: #fde8d0; color: #7a3f0c; }
    .badge[data-level="LOW"] { background: #eceeed; color: var(--muted); }
    .pico-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
    .pico-grid .study-field { padding: 10px; font-size: .84rem; }
    .edited-note { color: #684313; font-size: .8rem; }
    button.secondary { padding: 9px 16px; border: 1px solid var(--brand); background: transparent; color: var(--brand); }
    button.secondary:hover { background: #eef5f0; color: var(--brand-dark); }
    .depth-options { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 18px 0 10px; }
    .depth-option { display: flex; gap: 10px; margin: 0; padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: #fbfcf9; font-weight: 400; cursor: pointer; }
    .depth-option input { width: auto; margin-top: 4px; accent-color: var(--brand); }
    .depth-option:has(input:checked) { border-color: var(--brand); background: #eef5f0; }
    .depth-option strong { display: block; }
    .estimate { padding: 12px 14px; border-radius: 12px; background: #fff5df; color: #684313; font-size: .88rem; }
    .export-actions { display: flex; gap: 10px; flex-wrap: wrap; margin: 0 0 20px; }
    .export-actions a, .export-actions button { display: inline-block; padding: 10px 18px; border: 1px solid var(--brand); border-radius: 999px; background: var(--surface); color: var(--brand); font-weight: 800; text-decoration: none; font-size: .9rem; }
    .export-actions button:hover { background: #eef5f0; color: var(--brand-dark); transform: none; }
    .weighted { margin-top: 20px; padding: 24px; }
    .verdict-row { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }
    .verdict-row h2 { margin: 4px 0; }
    .weight-bars { display: grid; gap: 8px; margin: 16px 0; max-width: 620px; }
    .weight-bar { display: grid; grid-template-columns: 130px 1fr 56px; gap: 10px; align-items: center; font-size: .84rem; }
    .weight-bar .track { height: 10px; overflow: hidden; border-radius: 99px; background: #e6ebe7; }
    .weight-bar .fill { height: 100%; border-radius: 0 4px 4px 0; }
    .weight-bar .value { text-align: right; font-variant-numeric: tabular-nums; color: var(--muted); }
    .absence { margin-top: 12px; padding: 12px 14px; border-left: 4px solid var(--accent); border-radius: 8px; background: #fff8e9; font-size: .88rem; }
    .method-note { margin-top: 10px; color: var(--muted); font-size: .8rem; }
    .evidence-map { position: relative; margin-top: 14px; }
    .evidence-map svg { display: block; width: 100%; height: auto; }
    .map-tooltip { position: absolute; z-index: 2; max-width: 300px; padding: 9px 11px; border: 1px solid var(--line); border-radius: 9px; background: #fff; box-shadow: var(--shadow); font-size: .78rem; pointer-events: none; }
    .map-legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 6px; color: var(--muted); font-size: .78rem; }
    .map-legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; margin-right: 6px; border-radius: 50%; background: var(--dot); vertical-align: -1px; }
    .table-wrap { overflow-x: auto; margin-top: 12px; border: 1px solid var(--line); border-radius: 12px; }
    table.evidence-table { width: 100%; min-width: 1040px; border-collapse: collapse; background: #fff; font-size: .8rem; }
    .evidence-table th { padding: 9px 10px; background: #eef5f0; color: var(--brand-dark); text-align: left; white-space: nowrap; }
    .evidence-table td { padding: 9px 10px; border-top: 1px solid var(--line); vertical-align: top; }
    .evidence-table tr[data-status="RETRACTED"] td { background: #fff0ee; }
    .evidence-table .original { display: block; margin-top: 3px; color: var(--muted); font-size: .74rem; }
    .evidence-table details { margin-top: 6px; }
    .rel { font-weight: 800; white-space: nowrap; }
    .rel[data-relation="SUPPORTS"] { color: #1f6e50; }
    .rel[data-relation="CONTRADICTS"] { color: var(--danger); }
    .rel[data-relation="NEUTRAL"], .rel[data-relation="UNCERTAIN"] { color: #845c10; }
    .translated { color: #304039; font-style: italic; }
    dialog.preview { width: min(860px, calc(100% - 24px)); max-height: calc(100vh - 40px); padding: 0; border: 1px solid var(--line); border-radius: 18px; background: var(--surface); color: var(--ink); box-shadow: var(--shadow); }
    dialog.preview::backdrop { background: rgba(23, 34, 29, .45); }
    .preview-head { position: sticky; top: 0; z-index: 1; display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; padding: 18px 22px; border-bottom: 1px solid var(--line); background: var(--surface); }
    .preview-head h2 { margin: 2px 0; font-size: 1.35rem; }
    .preview-body { padding: 18px 22px 26px; overflow-wrap: anywhere; }
    .preview-body section + section { margin-top: 18px; }
    .preview-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
    .preview-links a { padding: 5px 11px; border: 1px solid var(--brand); border-radius: 999px; font-size: .8rem; font-weight: 700; text-decoration: none; }
    .passage { margin-top: 10px; padding: 11px 13px; border-left: 3px solid var(--line); border-radius: 6px; background: #fbfcf9; font-size: .86rem; }
    .passage .article-meta { display: block; margin-bottom: 4px; }
    mark { background: #ffe3a3; color: inherit; padding: 0 2px; border-radius: 3px; }
    .page-nav { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin: 10px 0; }
    .page-text { white-space: pre-wrap; font-size: .86rem; line-height: 1.6; padding: 14px; border: 1px solid var(--line); border-radius: 12px; background: #fff; max-height: 60vh; overflow: auto; }
    .attempts { margin: 6px 0 0; padding-left: 18px; color: var(--muted); font-size: .76rem; }
    .linklike { padding: 0; border: 0; background: none; color: var(--brand); font: inherit; font-weight: 750; text-align: left; text-decoration: underline; cursor: pointer; }
    .linklike:hover { background: none; color: var(--brand-dark); transform: none; }
    .complementary-status { margin-top: 10px; color: var(--muted); font-size: .86rem; }
    .trial-list { display: grid; gap: 6px; margin-top: 10px; font-size: .84rem; }
    .upload-pdf { display: inline-flex; align-items: center; gap: 6px; margin: 6px 0 0; color: var(--brand); font-size: .74rem; font-weight: 800; cursor: pointer; }
    .upload-pdf input { display: none; }
    .updates-list { display: grid; gap: 8px; margin-top: 12px; }
    .update-item { padding: 10px 12px; border: 1px solid var(--line); border-radius: 10px; background: #fbfcf9; font-size: .84rem; }
    .watch-toggle { display: inline-flex; align-items: center; gap: 8px; margin: 0; font-weight: 700; font-size: .88rem; }
    .watch-toggle input { width: auto; accent-color: var(--brand); }
    .status-flag { display: inline-block; margin-top: 4px; padding: 2px 7px; border-radius: 999px; background: #fff0ee; color: var(--danger); font-size: .7rem; font-weight: 800; }
    .status-flag[data-status="PREPRINT"], .status-flag[data-status="CORRECTED"] { background: #fff5df; color: #684313; }
    @media print {
      .mode, .form-panel, #claim-review, .export-actions, #claim-navigation, footer, button, .map-tooltip { display: none !important; }
      body { background: #fff; }
      .panel { box-shadow: none; break-inside: avoid-page; }
      .table-wrap { overflow: visible; }
      table.evidence-table { min-width: 0; }
    }
    @media (max-width: 760px) {
      header { display: block; }
      .mode { margin-top: 18px; max-width: none; }
      .result-grid { grid-template-columns: 1fr; }
      .indicator-grid { grid-template-columns: 1fr; }
      .claim-tabs, .crossing-flow { grid-template-columns: 1fr; }
      .study-grid, .report-columns { grid-template-columns: 1fr; }
      .pico-grid, .depth-options { grid-template-columns: 1fr; }
      .weight-bar { grid-template-columns: 100px 1fr 48px; }
    }
  </style>
  <link rel="stylesheet" href="/static/workspace.css">
  <link rel="stylesheet" href="/static/screens.css">
</head>
<body>
  <a class="skip-link" href="#workspace">Ir para a pesquisa</a>
  <aside class="sidebar" aria-label="Navegação principal">
    <a class="brand" href="/" aria-label="artfact — Início"><span class="brand-mark" aria-hidden="true">a.</span><span>artfact<small>Literatura em contexto</small></span></a>
    <div class="sidebar-caption">ÁREA DE TRABALHO</div>
    <nav class="side-nav">
      <button id="home-open" type="button" data-screen-nav="home" class="nav-item is-active"><span aria-hidden="true">⌂</span>Início</button>
      <button type="button" data-entry="search" data-screen-nav="home" class="nav-item"><span aria-hidden="true">⌕</span>Pesquisar artigos</button>
      <button type="button" data-entry="link" data-screen-nav="home" class="nav-item"><span aria-hidden="true">▤</span>Analisar um artigo</button>
      <a href="#article-library" id="library-open" data-screen-nav="library" class="nav-item"><span data-icon="library" aria-hidden="true"></span>Minha biblioteca</a>
      <button type="button" id="guide-open" class="nav-item"><span aria-hidden="true">ⓘ</span>Como funciona</button>
    </nav>
    <nav id="analysis-nav" class="analysis-nav" aria-label="Etapas da análise" hidden>
      <div class="sidebar-caption">ANÁLISE ATUAL</div>
      <button type="button" data-screen-nav="reading" class="nav-item"><span aria-hidden="true">01</span>Leitura</button>
      <button type="button" data-screen-nav="claims" class="nav-item"><span aria-hidden="true">02</span>Alegações</button>
      <button type="button" data-screen-nav="results" class="nav-item"><span aria-hidden="true">03</span>Resultados</button>
    </nav>
    <div class="sidebar-note"><span class="small-label">FONTES DE PESQUISA</span><div class="source-logos"><span>PubMed</span><span>PMC</span></div><p>Artigos, trechos e fontes disponíveis para você conferir.</p></div>
    <div class="sidebar-bottom"><span class="academic-dot"></span>Projeto acadêmico<small>Residência em Inteligência Artificial</small></div>
  </aside>
  <main id="workspace" class="shell">
    <div class="topbar"><span>Área de trabalho <span class="breadcrumb-separator">/</span> <strong id="screen-breadcrumb">Início</strong></span><div class="source-status" title="__MODE_LABEL__"><span></span>PubMed + PMC</div></div>
    <header class="workspace-header">
      <div class="eyebrow">LEITURA CIENTÍFICA ASSISTIDA</div>
      <h1>Uma leitura mais clara.<br><span>Com as fontes à vista.</span></h1>
      <p class="subtitle">Encontre estudos sobre um tema ou traga um artigo. Organize a leitura e compare os trechos com outras pesquisas.</p>
      <button id="change-source" type="button" class="secondary change-source" hidden>Começar outra leitura</button>
    </header>
    <ol class="workflow" aria-label="Etapas da pesquisa">
      <li data-step="1" class="is-current" aria-current="step"><span>01</span><div>Escolha a fonte<small>Pesquise ou envie um artigo</small></div></li>
      <li data-step="2"><span>02</span><div>Revise a leitura<small>Confira o que foi extraído</small></div></li>
      <li data-step="3"><span>03</span><div>Explore as evidências<small>Compare e confira os trechos</small></div></li>
    </ol>
    <section class="entry-workspace panel" aria-label="Começar uma pesquisa">
      <div class="entry-tabs" role="tablist" aria-label="Origem do artigo">
        <button id="tab-search" type="button" role="tab" aria-selected="true" aria-controls="topic-workspace" data-entry="search" class="entry-tab is-active">Pesquisar por tema</button>
        <button id="tab-link" type="button" role="tab" aria-selected="false" aria-controls="article-workspace" data-entry="link" class="entry-tab" tabindex="-1">Inserir link ou DOI</button>
        <button id="tab-upload" type="button" role="tab" aria-selected="false" aria-controls="article-workspace" data-entry="upload" class="entry-tab" tabindex="-1">Enviar arquivo</button>
      </div>
      <div class="entry-body">
      <div class="entry-main">
    <section id="topic-workspace" class="form-panel" role="tabpanel" aria-labelledby="tab-search">
      <div class="section-eyebrow">COMECE COM UMA PERGUNTA</div>
      <h2 id="topic-title">Encontre artigos por tema</h2>
      <p class="form-intro">O que você quer entender melhor? Pode escrever em português.</p>
      <form id="topic-form">
        <div class="field">
          <label for="topic-input">Seu tema de pesquisa</label>
          <input id="topic-input" minlength="2" maxlength="300" required placeholder="Ex.: exercício físico e diabetes tipo 2">
        </div>
        <div class="topic-filters">
          <div class="field filter-field">
            <label for="topic-type">Tipo de artigo</label>
            <select id="topic-type">
              <option value="ALL">Todos os tipos</option>
              <option value="REVIEWS">Revisões sistemáticas e meta-análises</option>
              <option value="TRIALS">Ensaios clínicos randomizados</option>
            </select>
          </div>
          <div class="field filter-field">
            <label for="topic-availability">Disponibilidade</label>
            <select id="topic-availability">
              <option value="ALL">Qualquer disponibilidade</option>
              <option value="PMC_FULL_TEXT">Texto completo gratuito no PMC</option>
            </select>
          </div>
          <div class="field filter-field">
            <label for="topic-indexing">Indexação</label>
            <select id="topic-indexing">
              <option value="MEDLINE" selected>Somente indexados no MEDLINE</option>
              <option value="ALL">Todos os registros do PubMed</option>
            </select>
          </div>
          <div class="field filter-field">
            <label for="topic-language">Idioma do artigo</label>
            <select id="topic-language">
              <option value="ALL">Todos os idiomas</option>
              <option value="PORTUGUESE">Português</option>
              <option value="ENGLISH">Inglês</option>
              <option value="SPANISH">Espanhol</option>
              <option value="FRENCH">Francês</option>
              <option value="GERMAN">Alemão</option>
              <option value="ITALIAN">Italiano</option>
            </select>
          </div>
          <div class="field filter-field filter-field-small">
            <label for="topic-page-size">Artigos analisados</label>
            <select id="topic-page-size">
              <option value="10">10 artigos</option>
              <option value="20" selected>20 artigos</option>
              <option value="50">50 artigos</option>
              <option value="100">100 artigos</option>
            </select>
          </div>
        </div>
        <label class="topic-theme-toggle">
          <input id="topic-clusters-enabled" type="checkbox" checked>
          <span><strong>Organizar resultados por temas</strong><small>Usa BERTopic e, quando disponível, IA para resumir os temas e revisar artigos sem grupo.</small></span>
        </label>
        <button id="topic-submit" type="submit">Pesquisar no PubMed <span aria-hidden="true">↗</span></button>
        <div class="suggestions" aria-label="Sugestões de pesquisa"><span>Experimente</span><button type="button" data-topic="Exercício físico e diabetes tipo 2">Exercício e diabetes</button><button type="button" data-topic="Terapia gênica para doenças hereditárias">Terapia gênica</button><button type="button" data-topic="Sono e saúde cardiovascular">Sono e saúde</button></div>
      </form>
      <p id="topic-status" class="hint" role="status" aria-live="polite"></p>
      <div id="topic-cluster-results"></div>
      <div id="topic-results"></div>
    </section>

    <section id="article-workspace" class="form-panel" role="tabpanel" aria-labelledby="tab-link" hidden>
      <div class="section-eyebrow">JÁ TEM UM ARTIGO?</div>
      <h2 id="form-title">Qual artigo você quer verificar?</h2>
      <p id="article-entry-description" class="form-intro">Cole a referência para começar a leitura.</p>
      <form id="analysis-form">
        <div id="link-field" class="field">
          <label for="article-reference">PMID, link do PubMed ou DOI indexado no PubMed</label>
          <input id="article-reference" maxlength="500" placeholder="PMID, https://pubmed.ncbi.nlm.nih.gov/... ou 10.xxxx/...">
          <p class="hint">A referência precisa estar indexada no PubMed.</p>
        </div>
        <div id="upload-field" class="field" hidden>
          <label for="article-file">Imagem ou arquivo do artigo</label>
          <div id="upload-zone" class="upload-zone">
            <span class="upload-icon" aria-hidden="true">↥</span><strong>Solte seu artigo aqui</strong><span>ou clique para escolher um arquivo</span>
          <input id="article-file" type="file" accept="application/pdf,image/png,image/jpeg,image/webp">
          </div>
          <p id="upload-name" class="hint" role="status"></p>
          <p class="hint">Formatos aceitos: PDF, PNG, JPEG e WebP, com até 25 MB.</p>
        </div>
        <div class="actions">
          <button id="submit" type="submit">Verificar artigo</button>
          <span class="hint">Você revisa a leitura antes da comparação.</span>
        </div>
      </form>
    </section>
      </div>
      <aside class="entry-context">
        <div class="context-orbit" aria-hidden="true"><div class="orbit-ring orbit-one"></div><div class="orbit-ring orbit-two"></div><span class="orbit-node node-one"></span><span class="orbit-node node-two"></span><span class="orbit-core">f.</span></div>
        <h3>Do artigo ao contexto.</h3><p>Uma leitura organizada, com os trechos originais sempre por perto.</p>
        <ul class="context-list"><li><span aria-hidden="true">▤</span>Estudos recuperados no PubMed</li><li><span aria-hidden="true">⌖</span>Citações com fonte e seção</li><li><span aria-hidden="true">◉</span>Limites da leitura visíveis</li></ul>
        <p class="context-footnote">A presença no PubMed não garante a qualidade de um estudo.</p>
      </aside>
      </div>
      <div class="workspace-bottom"><span>Pesquisa com fontes rastreáveis</span><span>PubMed / PMC</span></div>
    </section>
    <div class="safety-note">A ferramenta não oferece diagnóstico nem substitui profissionais de saúde. Confira as fontes e as interpretações.</div>
      <div id="status" role="status" aria-live="polite">
        <div class="status-row"><span id="status-text">Preparando análise…</span><span id="progress-text">0%</span></div>
        <div class="progress" role="progressbar" aria-label="Progresso da análise" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div id="progress-bar"></div></div>
        <p id="progress-detail" class="progress-detail">Aguardando o início do processamento.</p>
        <ol id="progress-stages" class="progress-stages" aria-label="Etapas do processamento">
          <li data-progress-stage="prepare">Preparar fonte</li>
          <li data-progress-stage="read">Ler e organizar</li>
          <li data-progress-stage="review">Revisar conteúdo</li>
          <li data-progress-stage="research">Buscar evidências</li>
          <li data-progress-stage="finish">Finalizar</li>
        </ol>
      </div>
      <div id="error" role="alert"></div>

    <section id="claim-pipeline" class="panel" hidden>
      <div class="actions"><strong>Alegações deste artigo</strong><button id="save-current-article" type="button" class="secondary">Guardar na biblioteca</button></div>
      <div id="claim-pipeline-tabs" class="claim-tabs" aria-label="Navegação entre alegações"></div>
    </section>
    <details id="source-reader" class="panel source-reader" hidden open>
      <summary>Artigo fonte e alegações marcadas</summary>
      <div class="reader-heading"><div><div class="kicker">TEXTO ORIGINAL</div><h2 id="reader-title">Artigo enviado</h2><p id="reader-scope" class="article-meta"></p></div><span class="reader-legend"><mark>Trecho de origem</mark> Passe o mouse ou toque para explorar.</span></div>
      <p id="reader-status" role="status" aria-live="polite"></p>
      <button id="reader-retry" type="button" class="secondary" hidden>Tentar carregar o texto novamente</button>
      <div class="reader-layout"><article id="reader-document" aria-label="Texto disponível do artigo"></article><aside id="reader-sidebar" aria-label="Alegações extraídas do artigo"></aside></div>
    </details>

    <section id="whole-article-report" class="panel document-report" aria-labelledby="whole-report-title">
      <div class="kicker">02 · Leitura da fonte principal</div>
      <div class="document-report-heading"><h2 id="whole-report-title">Dossiê do artigo</h2><button id="whole-report-language" type="button" class="secondary" hidden aria-pressed="false">Ver no idioma original</button></div>
      <div id="whole-coverage" class="coverage-banner"></div>
      <button id="open-source-preview" type="button" class="secondary">Ver o artigo enviado (texto lido)</button>
      <h3>Pergunta e objetivo</h3>
      <p id="whole-purpose"></p>
      <p id="whole-question" class="evidence"></p>
      <div class="summary-box"><strong>Resumo em linguagem clara</strong><span id="whole-summary"></span></div>
      <div id="whole-study" class="study-grid"></div>
      <div class="report-columns">
        <section class="report-subpanel"><h3>Principais resultados</h3><div id="whole-findings"></div></section>
        <section class="report-subpanel"><h3>Limitações declaradas</h3><div id="whole-critical"></div></section>
      </div>
      <div class="report-columns">
        <section class="report-subpanel"><h3>Tabelas e figuras</h3><div id="whole-tables"></div></section>
        <section class="report-subpanel"><h3>Financiamento e conflitos de interesse</h3><div id="whole-funding"></div></section>
      </div>
      <details>
        <summary>Ver mapa completo das seções</summary>
        <div id="whole-sections" class="stack"></div>
      </details>
      <details>
        <summary>Ver glossário do artigo</summary>
        <div id="whole-glossary" class="stack"></div>
      </details>
    </section>

    <section id="claim-review" class="panel" aria-labelledby="claim-review-title">
      <div class="kicker">Etapa 2 de 3 · revisão humana antes da busca</div>
      <h2 id="claim-review-title">Escolha quais alegações investigar</h2>
      <p class="review-intro">Confira as afirmações e os trechos de origem. Você pode corrigir o texto e escolher o que deseja comparar com outras pesquisas.</p>
      <div id="review-claims" class="review-list"></div>
      <div class="actions"><button id="add-custom-claim" type="button" class="secondary">Adicionar minha alegação</button><button id="select-all-claims" type="button" class="secondary">Selecionar todas</button><button id="clear-claim-selection" type="button" class="secondary">Limpar seleção</button></div>
      <fieldset class="comparison-picker">
        <legend>Artigos usados na comparação</legend>
        <label><input type="radio" name="comparison-mode" value="AUTOMATIC" checked style="width:auto"> Buscar no PubMed</label>
        <label><input type="radio" name="comparison-mode" value="MANUAL" style="width:auto"> Comparar com artigos que eu escolher</label>
        <div id="manual-comparison-fields" hidden>
          <label for="comparison-references">Referências para comparar (uma por linha)</label>
          <textarea id="comparison-references" placeholder="PMID, link do PubMed ou DOI"></textarea>
          <label for="comparison-files">Adicionar PDFs de comparação</label>
          <input id="comparison-files" type="file" accept="application/pdf" multiple>
          <p id="manual-comparison-selected" class="hint">Você também pode escolher artigos da biblioteca abaixo.</p>
          <a href="#article-library">Escolher artigos da biblioteca</a>
        </div>
      </fieldset>
      <div class="depth-options" role="radiogroup" aria-label="Profundidade da busca">
        <label class="depth-option"><input type="radio" name="depth" value="QUICK" checked><span><strong>Busca rápida</strong><span id="depth-quick-detail" class="article-meta"></span></span></label>
        <label class="depth-option"><input type="radio" name="depth" value="DEEP"><span><strong>Busca ampliada</strong><span id="depth-deep-detail" class="article-meta"></span></span></label>
      </div>
      <div id="research-estimate" class="estimate"></div>
      <div class="actions">
        <button id="research-selected" type="button">Investigar selecionadas</button>
        <span id="selection-count" class="safety"></span>
      </div>
    </section>

    <section id="article-library" class="panel" aria-labelledby="library-title" tabindex="-1">
      <div class="library-heading"><div><div class="section-eyebrow">SEU ACERVO DE PESQUISA</div><h2 id="library-title">Minha biblioteca</h2></div><span id="library-count" class="library-count" aria-live="polite"></span></div>
      <p class="hint">Artigos lidos ficam guardados nesta instalação, junto das análises. Busque no título, texto e notas ou escolha referências para comparar.</p>
      <div class="actions"><input id="library-query" placeholder="Buscar na biblioteca" aria-label="Buscar na biblioteca"><button id="library-refresh" type="button" class="secondary">Buscar</button></div>
      <details><summary>Guardar referências ou PDFs</summary>
        <label for="library-references">Referências (uma por linha)</label><textarea id="library-references"></textarea>
        <label for="library-files">PDFs</label><input id="library-files" type="file" accept="application/pdf" multiple>
        <button id="library-add" type="button" class="secondary">Guardar artigos</button>
      </details>
      <p id="library-status" role="status" aria-live="polite"></p><div id="library-items" class="stack"></div>
    </section>
    <section id="result" aria-live="polite">
      <div class="export-actions">
        <a id="export-markdown" href="#" download>Baixar relatório (Markdown)</a>
        <button id="export-pdf" type="button">Salvar como PDF</button>
      </div>
      <section id="claim-navigation" class="panel claim-navigation" aria-labelledby="claims-title">
        <h3 id="claims-title">Alegações identificadas no artigo</h3>
        <p>Cada alegação possui busca, evidências e resultado próprios. Selecione uma para conferir.</p>
        <div id="claim-tabs" class="claim-tabs" role="tablist"></div>
      </section>
      <section class="indicator-grid" aria-label="Indicadores separados da análise">
        <article class="panel indicator-card">
          <div class="kicker">Cobertura da busca</div>
          <h3 id="coverage-label"></h3>
          <p id="coverage-detail"></p>
        </article>
        <article class="panel indicator-card">
          <div class="kicker">Compatibilidade das evidências</div>
          <h3 id="compatibility-label"></h3>
          <p id="compatibility-detail"></p>
        </article>
        <article class="panel indicator-card">
          <div class="kicker">Dados e fontes</div>
          <h3 id="methodology-label"></h3>
          <p id="methodology-detail"></p>
        </article>
        <p class="indicator-note">A aplicação não atribui nota de qualidade metodológica nem probabilidade de o artigo estar correto.</p>
      </section>
      <section id="structured-search" class="panel structured-search" aria-labelledby="structured-search-title">
        <div class="kicker">Pesquisa biomédica dinâmica</div>
        <h3 id="structured-search-title">NCBI Gene e ClinVar</h3>
        <p class="article-meta">Consulta acionada pela alegação atual. Estes registros são evidência estruturada auxiliar e não substituem os artigos do PubMed/PMC.</p>
        <p id="structured-search-status" class="article-meta">Consultando fontes estruturadas…</p>
        <div id="structured-search-grid" class="structured-search-grid"></div>
      </section>
      <section class="panel weighted" aria-labelledby="weighted-title">
        <div class="kicker">Balanço descritivo dos trechos</div>
        <div class="verdict-row"><h2 id="weighted-title"></h2><span id="weighted-certainty" class="badge"></span></div>
        <p id="weighted-explanation"></p>
        <ul id="certainty-reasons" class="attempts" aria-label="Limites do balanço descritivo"></ul>
        <div id="weighted-bars" class="weight-bars" aria-label="Contagem de artigos por relação textual"></div>
        <div id="weighted-absence" class="absence"></div>
        <p id="weighted-method" class="method-note"></p>
        <div class="actions" style="margin-top: 14px">
          <button id="complementary-search" type="button" class="secondary">Pesquisa complementar</button>
          <span class="safety">Amplia a consulta e procura artigos relacionados somente no PubMed, sem repetir o que já foi lido.</span>
        </div>
        <p id="complementary-status" class="complementary-status"></p>
        <div id="trial-registry"></div>
      </section>
      <section class="panel weighted" aria-labelledby="map-title">
        <div class="kicker">Linha do tempo e mapa de concordância</div>
        <h3 id="map-title">Estudos recuperados por ano de publicação</h3>
        <p class="article-meta">Cada ponto é um estudo. A faixa mostra a relação encontrada nos trechos. Pontos vazios foram encontrados, mas não lidos.</p>
        <div id="evidence-map" class="evidence-map"></div>
        <div class="map-legend" id="map-legend"></div>
      </section>
      <section class="panel weighted" aria-labelledby="references-title">
        <div class="kicker">Citações e bibliografias</div>
        <h3 id="references-title">Relações entre os artigos</h3>
        <p class="article-meta">Confira quais artigos referenciam outros deste conjunto e quais referências eles compartilham.</p>
        <button type="button" class="secondary" id="reference-comparison-check">Verificar referências</button>
        <p id="reference-comparison-status" role="status" aria-live="polite"></p>
        <div id="reference-comparison-content"></div>
      </section>
      <section class="panel weighted" aria-labelledby="updates-title">
        <div class="kicker">Atualização da literatura</div>
        <h3 id="updates-title">Novos estudos sobre esta alegação</h3>
        <p class="article-meta">Repete as consultas registradas e lista trabalhos que ainda não estavam nesta análise. Ao acompanhar, a verificação roda automaticamente a cada 24 horas enquanto a aplicação estiver ativa.</p>
        <div class="actions" style="margin-top: 10px">
          <button id="check-updates" type="button" class="secondary">Verificar novos estudos agora</button>
          <label class="watch-toggle"><input id="watch-toggle" type="checkbox"> Acompanhar esta análise</label>
        </div>
        <p id="updates-summary" class="article-meta"></p>
        <div id="updates-list" class="updates-list"></div>
      </section>
      <section class="panel weighted" aria-labelledby="table-title">
        <div class="kicker">Extração padronizada por estudo</div>
        <h3 id="table-title">Tabela de evidências</h3>
        <p class="article-meta">Títulos, informações declaradas e trechos traduzidos para o português; o original permanece disponível para conferência. Qualidade metodológica e risco de viés não são avaliados automaticamente.</p>
        <div class="table-wrap"><table class="evidence-table"><thead><tr>
          <th>Ano</th><th>Estudo</th><th>Tipo informado / declaração declarado</th><th>População (n)</th><th>Intervenção × comparador</th><th>Desfecho e efeito</th><th>Relação textual</th>
        </tr></thead><tbody id="evidence-rows"></tbody></table></div>
      </section>
      <div class="result-grid" style="margin-top: 20px">
        <article class="panel result-card">
          <div class="kicker">Resposta em linguagem clara</div>
          <p id="extracted-claim" class="evidence"></p>
          <p id="claim-quote" class="evidence"></p>
          <h2 id="headline"></h2>
          <p id="summary"></p>
          <div class="summary-box">
            <strong>Como interpretar</strong>
            <span id="interpretation"></span>
          </div>
        </article>
        <aside class="panel result-card">
          <h3>O que conseguimos ler</h3>
          <p id="reading-summary"></p>
          <h3>Próximo passo recomendado</h3>
          <p id="next-action"></p>
        </aside>
      </div>
      <section class="panel crossing" aria-labelledby="crossing-title">
        <div class="kicker">Rastreabilidade</div>
        <h3 id="crossing-title">Como os dados foram cruzados</h3>
        <div class="crossing-flow">
          <div class="crossing-step"><strong id="cross-candidates">0</strong><span>candidatos encontrados</span></div>
          <div class="crossing-step"><strong id="cross-evaluated">0</strong><span>avaliados por relevância</span></div>
          <div class="crossing-step"><strong id="cross-accepted">0</strong><span>mantidos para leitura</span></div>
          <div class="crossing-step"><strong id="cross-assessed">0</strong><span>comparados com a alegação</span></div>
        </div>
        <strong>Bases e caminhos de descoberta</strong>
        <div id="cross-sources" class="chip-list"></div>
        <details>
          <summary>Ver consultas e estratégias utilizadas</summary>
          <ul id="cross-queries"></ul>
        </details>
      </section>
      <details id="article-dossier" class="panel result-card">
        <summary>Ver ficha do artigo enviado</summary>
        <div class="stack" id="dossier-items"></div>
      </details>
      <div class="panel result-card" style="margin-top: 20px">
        <div class="kicker">Trechos que sustentam a comparação</div>
        <h3>Evidências independentes encontradas</h3>
        <div class="stack" id="findings"></div>
      </div>
      <div class="result-grid" style="margin-top: 20px">
        <article class="panel result-card">
          <h3>Limitações desta análise</h3>
          <ul id="limitations"></ul>
        </article>
        <aside class="panel result-card">
          <h3>Fontes para conferência manual</h3>
          <ul id="sources"></ul>
        </aside>
      </div>
      <details class="panel result-card">
        <summary>Ver detalhes técnicos e alertas</summary>
        <p id="technical-coverage"></p>
        <h3>Reprodução</h3>
        <ul id="reproducibility"></ul>
        <ul id="verification-alerts" class="alert-list"></ul>
      </details>
    </section>

    <dialog id="preview-dialog" class="preview" aria-labelledby="preview-title">
      <div class="preview-head">
        <div><div id="preview-kicker" class="kicker"></div><h2 id="preview-title"></h2><div id="preview-meta" class="article-meta"></div></div>
        <button id="preview-close" type="button" class="secondary" aria-label="Fechar prévia">Fechar</button>
      </div>
      <div id="preview-body" class="preview-body"></div>
    </dialog>

    <footer><span>artfact · Projeto acadêmico</span><span>Qualidade metodológica não avaliada automaticamente.</span></footer>
  </main>
  <script>
    const form = document.getElementById('analysis-form');
    const submit = document.getElementById('submit');
    const statusBox = document.getElementById('status');
    const statusText = document.getElementById('status-text');
    const progressText = document.getElementById('progress-text');
    const progressBar = document.getElementById('progress-bar');
    const errorBox = document.getElementById('error');
    const resultBox = document.getElementById('result');
    const claimReview = document.getElementById('claim-review');
    const reviewClaims = document.getElementById('review-claims');
    const researchSelected = document.getElementById('research-selected');
    const selectionCount = document.getElementById('selection-count');
    let activeStatusUrl = null;
    let activeSelectionUrl = null;
    let activeAnalysisId = null;
    let activeClaimId = null;
    let complementaryTimer = null;
    let activeEstimates = null;
    let activeTopicQuery = null;
    let activeTopicMode = null;
    let pipelineBusy = false;
    let pollGeneration = 0;
    let structuredSearchGeneration = 0;
    const relationLabels = {SUPPORTS: 'Compatível', CONTRADICTS: 'Incompatível', NEUTRAL: 'Neutro', UNCERTAIN: 'Incerto', NOT_ASSESSED: 'Não lido'};
    const editorialLabels = {RETRACTED: 'Retratado', EXPRESSION_OF_CONCERN: 'Manifestação de preocupação', PREPRINT: 'Pré-publicação', CORRECTED: 'Com correção'};
    const statusLabels = {
      UNKNOWN: 'Não informado', UNRESOLVED: 'Não resolvido', FOUND: 'Localizado', NOT_FOUND: 'Não localizado',
      CONFIRMED: 'Confirmado', MATCH: 'Compatível', MISMATCH: 'Divergente', INCONCLUSIVE: 'Inconclusivo',
      REPORTED: 'Informado', NOT_REPORTED: 'Não informado', DECLARED_NONE: 'Declara ausência',
      DECLARED_PRESENT: 'Declara presença', PREPRINT: 'Pré-publicação', RETRACTED: 'Retratado',
      SYSTEMATIC_REVIEW_META_ANALYSIS: 'Revisão sistemática ou meta-análise',
      RANDOMIZED_CLINICAL_TRIAL: 'Ensaio clínico randomizado', OBSERVATIONAL: 'Estudo observacional',
      OTHER: 'Outro desenho', EXPLICIT_TEXT: 'Texto explícito', PUBLICATION_TYPE: 'Tipo de publicação'
    };
    const statusLabel = value => statusLabels[value] || value || 'Não informado';
    const chartColors = {SUPPORTS: '#1f8a62', NEUTRAL: '#c98a12', UNCERTAIN: '#c98a12', CONTRADICTS: '#c0392b', NOT_ASSESSED: '#9aa49e'};

    const text = value => value == null ? 'Não informado' : String(value);
    const sectionLabel = value => ({
      Abstract: 'Resumo', Introduction: 'Introdução', Background: 'Contexto', Methods: 'Métodos',
      Methodology: 'Metodologia', Results: 'Resultados', Discussion: 'Discussão',
      Conclusions: 'Conclusões', Conclusion: 'Conclusão', References: 'Referências'
    })[value] || value;
    const formatPublicationDate = value => {
      if (!value) return null;
      const months = {Jan: 'jan.', Feb: 'fev.', Mar: 'mar.', Apr: 'abr.', May: 'mai.', Jun: 'jun.', Jul: 'jul.', Aug: 'ago.', Sep: 'set.', Oct: 'out.', Nov: 'nov.', Dec: 'dez.'};
      return String(value).replace(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/g, month => months[month]);
    };
    const safeUrl = value => {
      try { const url = new URL(value); return ['http:', 'https:'].includes(url.protocol) ? url.href : null; }
      catch (_) { return null; }
    };
    function clearNode(node) { while (node.firstChild) node.removeChild(node.firstChild); }
    function addTextElement(parent, tag, value, className) {
      const element = document.createElement(tag); element.textContent = text(value);
      if (className) element.className = className; parent.appendChild(element); return element;
    }
    function showError(message) {
      setWorkflowStep(1);
      errorBox.textContent = message; errorBox.style.display = 'block';
      statusBox.style.display = 'none'; submit.disabled = false;
    }
    function setProgress(status, progress) {
      setWorkflowStep(status === 'RESEARCHING' ? 3 : 2);
      const states = {
        QUEUED: ['Análise na fila…', 'A fonte foi recebida e aguarda o início da leitura.', 'prepare'],
        RUNNING: ['Lendo e organizando o artigo…', 'Extraindo o conteúdo, as seções e os trechos que serão apresentados para revisão.', 'read'],
        AWAITING_CLAIM_SELECTION: ['Leitura pronta para revisão', 'Confira o conteúdo extraído e escolha o que deseja pesquisar.', 'review'],
        RESEARCHING: ['Pesquisando evidências no PubMed…', 'Recuperando estudos e organizando os trechos relacionados à sua seleção.', 'research'],
        SUCCEEDED: ['Análise concluída', 'O resultado foi organizado e está pronto para conferência.', 'finish'],
        FAILED: ['Não foi possível concluir', 'O processamento foi interrompido. Consulte a mensagem de erro para tentar novamente.', 'finish']
      };
      const current = states[status] || ['Preparando resultado…', 'Organizando as informações disponíveis.', 'prepare'];
      const normalized = Math.max(0, Math.min(100, Number(progress) || 0));
      statusText.textContent = current[0];
      document.getElementById('progress-detail').textContent = current[1];
      progressText.textContent = `${normalized}%`; progressBar.style.width = `${normalized}%`;
      const progressNode = progressBar.parentElement;
      progressNode.setAttribute('aria-valuenow', String(normalized));
      const order = ['prepare', 'read', 'review', 'research', 'finish'];
      const currentIndex = order.indexOf(current[2]);
      document.querySelectorAll('[data-progress-stage]').forEach((item, index) => {
        item.classList.toggle('is-done', index < currentIndex || status === 'SUCCEEDED');
        item.classList.toggle('is-current', index === currentIndex && status !== 'SUCCEEDED');
      });
    }
    function addCitation(parent, citation) {
      const node = document.createElement('div'); node.className = 'citation';
      node.dataset.verified = citation.verified === true ? 'true' : 'false';
      const location = [sectionLabel(citation.section), citation.page ? `p. ${citation.page}` : null].filter(Boolean).join(', ');
      node.textContent = `“${citation.quote || 'Trecho não fornecido'}”${location ? ` — ${location}` : ''}`;
      if (citation.verified === false) node.title = 'Trecho não localizado automaticamente no texto extraído.';
      parent.appendChild(node);
    }
    function renderWholeArticle(report, showOriginal = false) {
      const panel = document.getElementById('whole-article-report');
      if (!report) { panel.style.display = 'none'; return; }
      panel.style.display = 'block';
      const sourceReport = report;
      const originalNarrative = report.original_narrative || [];
      if (showOriginal && originalNarrative.length) {
        report = JSON.parse(JSON.stringify(report));
        originalNarrative.forEach(entry => {
          let target = report;
          const path = entry.path || [];
          for (const part of path.slice(0, -1)) {
            if (target?.[part] == null) return;
            target = target[part];
          }
          if (path.length && target != null) target[path[path.length - 1]] = entry.text;
        });
      }
      const reportLanguage = document.getElementById('whole-report-language');
      reportLanguage.hidden = !originalNarrative.length;
      reportLanguage.setAttribute('aria-pressed', String(showOriginal));
      reportLanguage.textContent = showOriginal ? 'Voltar para português' : 'Ver no idioma original';
      reportLanguage.onclick = () => renderWholeArticle(sourceReport, !showOriginal);
      const coverage = report.coverage || {};
      const coverageNode = document.getElementById('whole-coverage');
      coverageNode.dataset.complete = coverage.full_article_available === true ? 'true' : 'false';
      if (report.status === 'UNAVAILABLE') {
        coverageNode.textContent = `O dossiê integral não ficou disponível: ${report.error || 'falha não especificada'}`;
      } else if (coverage.full_article_available) {
        const sectionCoverage = coverage.section_coverage_percentage == null ? '' : ` · ${coverage.section_coverage_percentage}% das seções mapeadas`;
        coverageNode.textContent = `Texto completo processado${coverage.page_count ? ` · ${coverage.page_count} páginas` : ''}${sectionCoverage}.`;
      } else {
        coverageNode.textContent = `${coverage.scope_label || `Leitura parcial (${coverage.content_scope || 'escopo desconhecido'})`}. Para uma análise realmente integral e citações por página, envie o PDF completo.`;
      }
      const overview = report.overview || {};
      document.getElementById('whole-purpose').textContent = text(overview.purpose);
      document.getElementById('whole-question').textContent = overview.research_question ? `Pergunta central: ${overview.research_question}` : '';
      document.getElementById('whole-summary').textContent = text(overview.plain_language_summary);

      const study = report.study || {};
      const studyFields = [
        ['Desenho declarado no texto', study.design], ['População', study.population], ['Amostra mencionada no texto', study.sample_size],
        ['Intervenção/exposição', study.intervention_or_exposure], ['Comparador', study.comparator],
        ['Seguimento', study.follow_up], ['Desfechos', (study.outcomes || []).join('; ')],
        ['Métodos estatísticos', (study.statistical_methods || []).join('; ')]
      ];
      const studyNode = document.getElementById('whole-study'); clearNode(studyNode);
      const studySources = report.study_field_sources || {};
      studyFields.filter(([, value]) => value && value !== 'Não informado').forEach(([label, value]) => {
        const field = document.createElement('div'); field.className = 'study-field';
        addTextElement(field, 'strong', label); addTextElement(field, 'span', value);
        Object.values(studySources).flat().filter(source => value.includes(source.text)).forEach(source => {
          addTextElement(field, 'small', `Trecho: “${source.quote}”${source.section ? ` — ${sectionLabel(source.section)}` : ''}${source.page ? `, p. ${source.page}` : ''}`);
        });
        studyNode.appendChild(field);
      });

      const findings = document.getElementById('whole-findings'); clearNode(findings);
      if (!(report.main_findings || []).length) addTextElement(findings, 'p', 'Nenhum resultado principal foi extraído com segurança.');
      (report.main_findings || []).forEach(item => {
        const card = document.createElement('article'); card.className = 'report-finding';
        addTextElement(card, 'strong', item.finding);
        if (item.numbers && item.numbers !== 'Não informado') addTextElement(card, 'p', `Números: ${item.numbers}`);
        addTextElement(card, 'p', item.interpretation);
        (item.citations || []).forEach(citation => addCitation(card, citation)); findings.appendChild(card);
      });

      const critical = document.getElementById('whole-critical'); clearNode(critical);
      if ((report.authors_declared_limitations || []).length) addTextElement(critical, 'strong', 'Limitações declaradas pelos autores');
      const declared = report.authors_declared_limitations || [];

      declared.forEach(item => {
        const block = document.createElement('div'); addTextElement(block, 'p', item.limitation);
        (item.citations || []).forEach(citation => addCitation(block, citation)); critical.appendChild(block);
      });

      const tables = document.getElementById('whole-tables'); clearNode(tables);
      const described = report.tables_figures || [];
      const detected = coverage.detected_tables_figures || [];
      const renderedFigurePages = new Set();
      if (!described.length && !detected.length) addTextElement(tables, 'p', 'Nenhuma tabela ou figura foi identificada no texto lido.');
      described.forEach(item => {
        const card = document.createElement('article'); card.className = 'report-finding';
        addTextElement(card, 'strong', `${item.label} — ${item.description}`);
        if (item.key_data && item.key_data !== 'Não informado') addTextElement(card, 'p', `Dados: ${item.key_data}`);
        if (item.page && activeAnalysisId && coverage.content_scope === 'LOCAL_PDF_FULL_TEXT' && !renderedFigurePages.has(item.page)) {
          renderedFigurePages.add(item.page);
          const figure = document.createElement('figure'); figure.className = 'article-page-figure';
          const image = document.createElement('img');
          image.src = `/api/v1/analyses/${encodeURIComponent(activeAnalysisId)}/source/pages/${item.page}/image`;
          image.alt = `Página ${item.page} do PDF contendo ${item.label || 'a tabela ou figura'}`;
          image.loading = 'lazy'; image.decoding = 'async';
          image.addEventListener('error', () => { figure.hidden = true; });
          const caption = document.createElement('figcaption');
          caption.textContent = `Imagem da página ${item.page} do PDF original. Use o texto acima para localizar os dados descritos.`;
          figure.append(image, caption); card.appendChild(figure);
        }
        tables.appendChild(card);
      });
      if (detected.length) {
        addTextElement(tables, 'p', `Legendas localizadas no texto extraído: ${detected.map(item => `${item.label}${item.page ? ` (p. ${item.page})` : ''}`).join(', ')}.`, 'article-meta');
      }
      const funding = document.getElementById('whole-funding'); clearNode(funding);
      const fundingStatus = {REPORTED: 'Financiamento declarado', NO_FUNDING_DECLARED: 'Declara não ter recebido financiamento', NOT_REPORTED: 'Financiamento não informado'};
      const conflictStatus = {DECLARED_NONE: 'Declara ausência de conflitos', DECLARED_PRESENT: 'Declara conflitos de interesse', NOT_REPORTED: 'Conflitos não informados'};
      const fundingBlock = report.funding || {}; const conflictBlock = report.conflicts_of_interest || {};
      if (fundingBlock.statement) addTextElement(funding, 'strong', 'Declaração de financiamento no texto');
      if (fundingBlock.statement) addTextElement(funding, 'p', fundingBlock.statement);
      if ((fundingBlock.sources || []).length) addTextElement(funding, 'p', `Fontes: ${fundingBlock.sources.join('; ')}`, 'article-meta');
      (fundingBlock.citations || []).forEach(citation => addCitation(funding, citation));
      if (conflictBlock.statement) addTextElement(funding, 'strong', 'Declaração de conflitos no texto');
      if (conflictBlock.statement) addTextElement(funding, 'p', conflictBlock.statement);
      (conflictBlock.citations || []).forEach(citation => addCitation(funding, citation));

      const sections = document.getElementById('whole-sections'); clearNode(sections);
      (report.section_summaries || []).forEach(item => {
        const card = document.createElement('article'); card.className = 'finding';
        addTextElement(card, 'h3', sectionLabel(item.section)); addTextElement(card, 'p', item.summary);
        const points = document.createElement('ul'); (item.key_points || []).forEach(point => addTextElement(points, 'li', point)); card.appendChild(points);
        (item.citations || []).forEach(citation => addCitation(card, citation)); sections.appendChild(card);
      });
      const glossary = document.getElementById('whole-glossary'); clearNode(glossary);
      (report.glossary || []).forEach(item => {
        const row = document.createElement('div'); row.className = 'study-field';
        addTextElement(row, 'strong', item.term); addTextElement(row, 'span', item.definition); glossary.appendChild(row);
      });
    }
    function renderWeighted(weighted) {
      const verdict = weighted.verdict || {};
      document.getElementById('weighted-title').textContent = text(verdict.label || 'Balanço descritivo indisponível');
      const certainty = document.getElementById('weighted-certainty');
      certainty.textContent = verdict.certainty_label ? `Certeza estimada ${verdict.certainty_label.toLowerCase()}` : '';
      certainty.style.display = verdict.certainty_label ? 'inline-block' : 'none';
      document.getElementById('weighted-explanation').textContent = verdict.explanation || 'Esta execução não produziu a tabela padronizada.';
      const reasons = document.getElementById('certainty-reasons'); clearNode(reasons);
      (verdict.certainty_reasons || []).forEach(item => addTextElement(reasons, 'li', item));
      const bars = document.getElementById('weighted-bars'); clearNode(bars);
      const totals = weighted.weighted || {};
      const entries = [['SUPPORTS', totals.supports || 0], ['NEUTRAL', totals.neutral || 0], ['CONTRADICTS', totals.contradicts || 0]];
      const maxWeight = Math.max(1, ...entries.map(([, value]) => value));
      entries.forEach(([relation, value]) => {
        const row = document.createElement('div'); row.className = 'weight-bar';
        addTextElement(row, 'span', relationLabels[relation]);
        const track = document.createElement('div'); track.className = 'track';
        const fill = document.createElement('div'); fill.className = 'fill';
        fill.style.width = `${(value / maxWeight) * 100}%`; fill.style.background = chartColors[relation];
        track.appendChild(fill); row.appendChild(track);
        addTextElement(row, 'span', value.toFixed(2), 'value'); bars.appendChild(row);
      });
      const absence = document.getElementById('weighted-absence');
      absence.textContent = weighted.absence?.message || '';
      absence.style.display = weighted.absence?.message ? 'block' : 'none';
      document.getElementById('weighted-method').textContent = weighted.method || '';
    }
    function renderEvidenceMap(rows) {
      const host = document.getElementById('evidence-map'); clearNode(host);
      const legend = document.getElementById('map-legend'); clearNode(legend);
      const dated = rows.filter(row => row.year);
      if (!dated.length) { addTextElement(host, 'p', 'Nenhum estudo com ano de publicação para posicionar na linha do tempo.', 'article-meta'); return; }
      const lanes = ['SUPPORTS', 'NEUTRAL', 'CONTRADICTS', 'NOT_ASSESSED'];
      const laneOf = row => row.relation === 'UNCERTAIN' ? 'NEUTRAL' : (lanes.includes(row.relation) ? row.relation : 'NOT_ASSESSED');
      const laneTitles = {SUPPORTS: 'Compatível', NEUTRAL: 'Neutro/incerto', CONTRADICTS: 'Incompatível', NOT_ASSESSED: 'Não lido'};
      const years = dated.map(row => row.year);
      let minYear = Math.min(...years), maxYear = Math.max(...years);
      if (minYear === maxYear) { minYear -= 1; maxYear += 1; }
      const width = 920, left = 118, right = 24, top = 14, laneHeight = 46, bottom = 30;
      const height = top + lanes.length * laneHeight + bottom;
      const x = year => left + ((year - minYear) / (maxYear - minYear)) * (width - left - right);
      const ns = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(ns, 'svg');
      svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'img');
      svg.setAttribute('aria-label', `Linha do tempo de ${dated.length} estudos entre ${Math.min(...years)} e ${Math.max(...years)}`);
      const make = (tag, attrs) => { const node = document.createElementNS(ns, tag); Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value)); return node; };
      lanes.forEach((lane, index) => {
        const y = top + index * laneHeight + laneHeight / 2;
        svg.appendChild(make('line', {x1: left, x2: width - right, y1: y, y2: y, stroke: '#e3e8e4', 'stroke-width': 1}));
        const label = make('text', {x: left - 12, y: y + 4, 'text-anchor': 'end', 'font-size': 12, fill: '#5d6a64'});
        label.textContent = laneTitles[lane]; svg.appendChild(label);
      });
      const span = maxYear - minYear;
      const step = span <= 10 ? 1 : span <= 25 ? 5 : 10;
      for (let year = Math.ceil(minYear / step) * step; year <= maxYear; year += step) {
        const tick = make('text', {x: x(year), y: height - 8, 'text-anchor': 'middle', 'font-size': 11, fill: '#5d6a64'});
        tick.textContent = year; svg.appendChild(tick);
      }
      const tooltip = document.createElement('div'); tooltip.className = 'map-tooltip'; tooltip.hidden = true;
      const placed = {};
      dated.slice().sort((a, b) => (b.weight || 0) - (a.weight || 0)).forEach(row => {
        const lane = laneOf(row); const laneIndex = lanes.indexOf(lane);
        const key = `${lane}:${row.year}`; const stack = placed[key] = (placed[key] || 0) + 1;
        const offset = stack === 1 ? 0 : (stack % 2 ? 1 : -1) * Math.ceil((stack - 1) / 2) * 9;
        const cx = x(row.year), cy = top + laneIndex * laneHeight + laneHeight / 2 + Math.max(-18, Math.min(18, offset));
        const radius = row.assessed ? 5 + Math.min(1, row.weight || 0) * 9 : 5;
        const color = chartColors[lane];
        const dot = make('circle', {cx, cy, r: radius, fill: row.assessed ? color : '#fff', 'fill-opacity': row.assessed ? .85 : 1, stroke: row.assessed ? '#fff' : color, 'stroke-width': 2});
        if (row.editorial_status === 'RETRACTED') { dot.setAttribute('stroke', '#9b3d31'); dot.setAttribute('stroke-dasharray', '3 2'); }
        const hit = make('circle', {cx, cy, r: Math.max(radius, 12), fill: 'transparent'});
        const show = () => {
          tooltip.textContent = '';
          const title = document.createElement('strong'); title.textContent = `${row.year} · ${row.title_pt || row.title}`; tooltip.appendChild(title);
          const detail = document.createElement('div');
          detail.textContent = [relationLabels[row.relation] || row.relation, row.publication_types_source ? (row.publication_types || []).join('; ') + ' · PubMed' : null, editorialLabels[row.editorial_status]].filter(Boolean).join(' · ');
          tooltip.appendChild(detail);
          const box = host.getBoundingClientRect(); const scale = box.width / width;
          tooltip.style.left = `${Math.min(box.width - 300, Math.max(0, cx * scale + 12))}px`; tooltip.style.top = `${cy * scale + 12}px`;
          tooltip.hidden = false;
        };
        hit.addEventListener('mouseenter', show); hit.addEventListener('mouseleave', () => { tooltip.hidden = true; });
        hit.addEventListener('click', () => {
          const target = document.querySelector(`[data-row-key="${CSS.escape(row.doi || row.pmid || row.url || '')}"]`);
          if (target) target.scrollIntoView({behavior: 'smooth', block: 'center'});
        });
        svg.appendChild(dot); svg.appendChild(hit);
      });
      host.appendChild(svg); host.appendChild(tooltip);
      [['SUPPORTS', 'Compatível'], ['NEUTRAL', 'Neutro/incerto'], ['CONTRADICTS', 'Incompatível'], ['NOT_ASSESSED', 'Não lido (vazado)']].forEach(([key, label]) => {
        const item = document.createElement('span'); item.textContent = label; item.style.setProperty('--dot', chartColors[key]); legend.appendChild(item);
      });
    }
    function renderEvidenceTable(rows) {
      const body = document.getElementById('evidence-rows'); clearNode(body);
      if (!rows.length) {
        const tr = document.createElement('tr'); const td = document.createElement('td'); td.colSpan = 10;
        td.textContent = 'Nenhum estudo foi recuperado para esta alegação.'; tr.appendChild(td); body.appendChild(tr); return;
      }
      const ordered = rows.slice().sort((a, b) => (b.weight || 0) - (a.weight || 0) || (b.year || 0) - (a.year || 0));
      const cell = (tr, value) => { const td = document.createElement('td'); if (value instanceof Node) td.appendChild(value); else td.textContent = value == null || value === '' ? '—' : String(value); tr.appendChild(td); return td; };
      ordered.forEach(row => {
        const tr = document.createElement('tr'); tr.dataset.status = row.editorial_status || '';
        tr.dataset.rowKey = row.doi || row.pmid || row.url || '';
        cell(tr, row.year);
        const study = document.createElement('div');
        const titleNode = document.createElement('button'); titleNode.type = 'button'; titleNode.className = 'linklike';
        titleNode.textContent = row.title_pt || row.title || 'Sem título';
        titleNode.title = 'Abrir prévia do estudo';
        titleNode.addEventListener('click', () => openStudyPreview(row));
        study.appendChild(titleNode);
        if (row.title_pt && row.title && row.title_pt !== row.title) addTextElement(study, 'span', row.title, 'original');
        addTextElement(study, 'span', [row.journal, row.is_medline ? 'Indexado no MEDLINE' : null, row.access_level === 'ABSTRACT_ONLY' ? 'lido: somente o resumo' : (row.assessed ? 'lido: texto completo' : 'não lido')].filter(Boolean).join(' · '), 'original');
        if (editorialLabels[row.editorial_status]) { const flag = addTextElement(study, 'span', editorialLabels[row.editorial_status], 'status-flag'); flag.dataset.status = row.editorial_status; }
        const fullTextLevels = ['FULL_TEXT', 'OPEN_ACCESS_FULL_TEXT', 'USER_PROVIDED_FULL_TEXT'];
        if (!fullTextLevels.includes(row.access_level) && activeClaimId && row.work_key) {
          const upload = document.createElement('label'); upload.className = 'upload-pdf';
          upload.textContent = row.assessed ? 'Enviar PDF completo e reavaliar' : 'Enviar PDF deste estudo';
          const input = document.createElement('input'); input.type = 'file'; input.accept = 'application/pdf';
          input.addEventListener('change', () => input.files[0] && uploadStudyPdf(row.work_key, input.files[0], upload));
          upload.appendChild(input); study.appendChild(upload);
        }
        if ((row.authors || []).length) addTextElement(study, 'span', `Autores: ${row.authors.join('; ')} · PubMed`, 'original');
        const identifiers = [row.pmid ? `PMID ${row.pmid}` : null, row.doi ? `DOI ${row.doi}` : null, row.pmcid].filter(Boolean);
        if (identifiers.length) addTextElement(study, 'span', identifiers.join(' · '), 'original');
        if (row.full_text_source) addTextElement(study, 'span', `Texto: ${row.full_text_source}`, 'original');
        if (row.assessed && !fullTextLevels.includes(row.access_level) && (row.full_text_attempts || []).length) {
          const last = row.full_text_attempts[row.full_text_attempts.length - 1];
          addTextElement(study, 'span', `Sem texto completo: ${last.outcome}`, 'original');
        }
        if (row.same_population_as_submitted) addTextElement(study, 'span', `Mesmo estudo/população do artigo enviado (${row.duplicate_group}): não conta como confirmação independente`, 'status-flag');
        else if (row.duplicate_group) addTextElement(study, 'span', `Mesma população: ${row.duplicate_group}`, 'status-flag').dataset.status = 'PREPRINT';
        if (row.assessed && (row.finding_pt || row.quote)) {
          const more = document.createElement('details');
          addTextElement(more, 'summary', 'Achado e trecho citado');
          if (row.finding_pt) addTextElement(more, 'p', row.finding_pt);
          if (row.quote_pt) addTextElement(more, 'p', `“${row.quote_pt}”`, 'translated');
          if (row.quote) addTextElement(more, 'p', `Original: “${row.quote}”${row.quote_section ? ` — ${row.quote_section}` : ''}`, 'original');
          if (row.rationale) addTextElement(more, 'p', `Classificação: ${row.rationale}`, 'original');
          study.appendChild(more);
        }
        cell(tr, study);
        if (Object.keys(row.field_sources || {}).length) {
          const sources = document.createElement('details');
          addTextElement(sources, 'summary', 'Fontes dos dados extraídos');
          Object.entries(row.field_sources).forEach(([field, source]) => {
            addTextElement(sources, 'p', `${field}: “${source.quote || source.text}” — ${sectionLabel(source.section) || 'seção não identificada'}${source.page ? `, p. ${source.page}` : ''}`);
            previewLink(sources, 'Conferir fonte', source.source_url || row.url);
          });
          study.appendChild(sources);
        }
        const methodology = document.createElement('div');
        if (row.publication_types_source) addTextElement(methodology, 'span', `${(row.publication_types || []).join('; ')} · ${row.publication_types_source}`);
        if (row.design_detail) addTextElement(methodology, 'span', `Declaração no texto: “${row.design_detail}”`);
        if (row.comparability_label) addTextElement(methodology, 'span', `Comparabilidade PICO: ${row.comparability_label}`, 'original');
        if (row.rob_label) addTextElement(methodology, 'span', `Risco de viés: ${row.rob_label}${row.rob_tool_label ? ` · ${row.rob_tool_label}` : ''}`, 'original');
        if ((row.rob_domains || []).length) {
          const domains = document.createElement('details');
          addTextElement(domains, 'summary', 'Ver domínios metodológicos');
          row.rob_domains.forEach(item => addTextElement(domains, 'p', `${item.domain}: ${item.judgment}${item.reason ? ` — ${item.reason}` : ''}`, 'original'));
          methodology.appendChild(domains);
        }
        cell(tr, methodology);
        cell(tr, [row.population, row.sample_size ? `Menção no texto: ${row.sample_size}` : null].filter(Boolean).join(' · '));
        cell(tr, [row.intervention_or_exposure, row.comparator].filter(Boolean).join(' × '));
        cell(tr, [row.outcome, row.effect_estimate].filter(Boolean).join(' — '));
        const relation = document.createElement('span'); relation.className = 'rel'; relation.dataset.relation = row.relation;
        relation.textContent = relationLabels[row.relation] || row.relation; cell(tr, relation);
        body.appendChild(tr);
      });
    }
    async function fileToBase64(file) {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = ''; const block = 0x8000;
      for (let index = 0; index < bytes.length; index += block) binary += String.fromCharCode(...bytes.subarray(index, index + block));
      return btoa(binary);
    }
    async function callTool(url, options, busyNode, busyText) {
      const original = busyNode ? busyNode.textContent : null;
      try {
        errorBox.style.display = 'none';
        if (busyNode) { busyNode.textContent = busyText; busyNode.setAttribute('aria-busy', 'true'); }
        const response = await fetch(url, options);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || 'A ação não pôde ser concluída.');
        renderAnalysis(payload.result, false);
      } catch (error) {
        if (busyNode) busyNode.textContent = original;
        showError(error.message || 'Erro inesperado.');
      } finally {
        if (busyNode) busyNode.removeAttribute('aria-busy');
      }
    }
    async function uploadStudyPdf(studyKey, file, node) {
      if (file.size > 25 * 1024 * 1024) { showError('O PDF deve ter no máximo 25 MB.'); return; }
      const data = await fileToBase64(file);
      await callTool(`/api/v1/analyses/${activeAnalysisId}/claims/${encodeURIComponent(activeClaimId)}/studies/full-text`, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({study_key: studyKey, article_file: {name: file.name, mime_type: 'application/pdf', data_base64: data}})
      }, node, 'Lendo PDF e reavaliando…');
    }
    function renderUpdates(data) {
      const updates = data.updates;
      const summary = document.getElementById('updates-summary');
      const list = document.getElementById('updates-list'); clearNode(list);
      if (!updates) { summary.textContent = 'Ainda não verificado.'; return; }
      const checked = new Date(updates.checked_at).toLocaleString('pt-BR');
      summary.textContent = updates.new_study_count
        ? `${updates.new_study_count} trabalho(s) ainda não incluído(s) nesta análise · verificado em ${checked}.`
        : `Nenhum trabalho novo encontrado pelas mesmas consultas · verificado em ${checked}.`;
      (updates.new_studies || []).forEach(item => {
        const node = document.createElement('div'); node.className = 'update-item';
        const url = safeUrl(item.url);
        const title = document.createElement(url ? 'a' : 'strong'); title.textContent = item.title || 'Sem título';
        if (url) { title.href = url; title.target = '_blank'; title.rel = 'noopener noreferrer'; }
        node.appendChild(title);
        addTextElement(node, 'div', [item.year, item.journal, (item.sources || []).join(', '), item.published_after_analysis ? 'publicado após a análise' : null].filter(Boolean).join(' · '), 'article-meta');
        list.appendChild(node);
      });
    }
    document.getElementById('check-updates').addEventListener('click', event => callTool(
      `/api/v1/analyses/${activeAnalysisId}/new-studies`,
      {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({claim_id: activeClaimId})},
      event.currentTarget, 'Verificando…'));
    document.getElementById('watch-toggle').addEventListener('change', event => callTool(
      `/api/v1/analyses/${activeAnalysisId}/watch`,
      {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({enabled: event.currentTarget.checked})}));
    const previewDialog = document.getElementById('preview-dialog');
    document.getElementById('preview-close').addEventListener('click', () => previewDialog.close());
    previewDialog.addEventListener('click', event => { if (event.target === previewDialog) previewDialog.close(); });
    function escapeRegExp(value) { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
    function appendHighlighted(parent, content, quotes) {
      const valid = (quotes || []).map(item => (item || '').trim()).filter(item => item.length >= 12);
      if (!valid.length) { parent.appendChild(document.createTextNode(content)); return 0; }
      const normalized = valid.map(item => escapeRegExp(item).replace(/\s+/g, '\\s+'));
      const pattern = new RegExp(`(${normalized.join('|')})`, 'gi');
      let last = 0, count = 0, match;
      while ((match = pattern.exec(content))) {
        parent.appendChild(document.createTextNode(content.slice(last, match.index)));
        const mark = document.createElement('mark'); mark.textContent = match[0]; parent.appendChild(mark);
        last = match.index + match[0].length; count += 1;
      }
      parent.appendChild(document.createTextNode(content.slice(last)));
      return count;
    }
    function previewLink(parent, label, url) {
      const safe = safeUrl(url); if (!safe) return;
      const link = document.createElement('a'); link.href = safe; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = label; parent.appendChild(link);
    }
    let activeArticles = [];
    function articleFor(row) {
      return activeArticles.find(item => (item.work_key || item.pmid || (item.doi ? `doi:${item.doi}` : null)) === row.work_key) || {};
    }
    function openStudyPreview(row) {
      const article = articleFor(row);
      row = {...row, abstract: article.abstract, analyzed_passages: article.analyzed_passages || [], authors: article.authors || []};
      document.getElementById('preview-kicker').textContent = 'Estudo comparado';
      document.getElementById('preview-title').textContent = row.title_pt || row.title || 'Sem título';
      document.getElementById('preview-meta').textContent = [row.year, row.journal, (row.authors || []).slice(0, 3).join(', '), row.design_label].filter(Boolean).join(' · ');
      const body = document.getElementById('preview-body'); clearNode(body);
      if (row.title_pt && row.title && row.title_pt !== row.title) addTextElement(body, 'p', `Título original: ${row.title}`, 'article-meta');
      const links = document.createElement('div'); links.className = 'preview-links';
      previewLink(links, 'Abrir na fonte', row.url);
      if (row.doi) previewLink(links, 'DOI', `https://doi.org/${row.doi}`);
      if (row.pmid) previewLink(links, 'PubMed', `https://pubmed.ncbi.nlm.nih.gov/${row.pmid}/`);
      previewLink(links, 'Texto completo (PMC)', row.pmc_url);
      body.appendChild(links);
      const access = document.createElement('section');
      addTextElement(access, 'h3', 'O que foi lido');
      const levelLabel = {FULL_TEXT: 'Texto completo', OPEN_ACCESS_FULL_TEXT: 'Texto completo aberto', USER_PROVIDED_FULL_TEXT: 'PDF enviado por você', ABSTRACT_ONLY: 'Somente o resumo', METADATA_ONLY: 'Somente metadados (não lido)'};
      addTextElement(access, 'p', `${levelLabel[row.access_level] || row.access_level}${row.full_text_source ? ` — via ${row.full_text_source}` : ''}.`);
      if ((row.full_text_attempts || []).length) {
        addTextElement(access, 'strong', 'Tentativas de obter o texto completo');
        const list = document.createElement('ul'); list.className = 'attempts';
        row.full_text_attempts.forEach(item => addTextElement(list, 'li', `${item.source}: ${item.outcome}`));
        access.appendChild(list);
      }
      body.appendChild(access);
      if (row.assessed) {
        const finding = document.createElement('section');
        addTextElement(finding, 'h3', `Relação com a alegação: ${relationLabels[row.relation] || row.relation}`);
        if (row.finding_pt) addTextElement(finding, 'p', row.finding_pt);
        if (row.rationale) addTextElement(finding, 'p', row.rationale, 'article-meta');
        if (row.quote_pt) addTextElement(finding, 'p', `“${row.quote_pt}”`, 'translated');
        body.appendChild(finding);
      }
      if ((row.analyzed_passages || []).length) {
        const passages = document.createElement('section');
        addTextElement(passages, 'h3', 'Trechos lidos pelo modelo');
        addTextElement(passages, 'p', 'Destaque amarelo = trecho citado como evidência.', 'article-meta');
        row.analyzed_passages.forEach(item => {
          const node = document.createElement('div'); node.className = 'passage';
          addTextElement(node, 'span', [sectionLabel(item.section), item.page ? `p. ${item.page}` : null].filter(Boolean).join(' · ') || 'Trecho', 'article-meta');
          const textNode = document.createElement('div'); appendHighlighted(textNode, item.text || '', [row.quote]); node.appendChild(textNode);
          passages.appendChild(node);
        });
        body.appendChild(passages);
      } else if (row.abstract) {
        const abstract = document.createElement('section');
        addTextElement(abstract, 'h3', 'Resumo');
        const textNode = document.createElement('p'); appendHighlighted(textNode, row.abstract, [row.quote]); abstract.appendChild(textNode);
        body.appendChild(abstract);
      }
      previewDialog.showModal();
    }
    async function openSourcePreview() {
      if (!activeAnalysisId) return;
      try {
        const response = await fetch(`/api/v1/analyses/${activeAnalysisId}/source`);
        const source = await response.json();
        if (!response.ok) throw new Error(source.error?.message || 'Não foi possível abrir o artigo.');
        document.getElementById('preview-kicker').textContent = 'Artigo enviado';
        document.getElementById('preview-title').textContent = source.title || source.source || 'Artigo enviado';
        document.getElementById('preview-meta').textContent = [source.journal, source.publication_date, (source.authors || []).slice(0, 3).join(', '), source.parser ? `leitura: ${source.parser}` : null].filter(Boolean).join(' · ');
        const body = document.getElementById('preview-body'); clearNode(body);
        const links = document.createElement('div'); links.className = 'preview-links';
        previewLink(links, 'Abrir original', source.source_url || (source.doi ? `https://doi.org/${source.doi}` : null));
        body.appendChild(links);
        const quotes = (source.claims || []).map(item => item.quote).filter(Boolean);
        const units = (source.pages || []).length
          ? source.pages.map(item => ({label: `Página ${item.page_number}`, text: item.text}))
          : (source.sections || []).length
            ? source.sections.map(item => ({label: item.title, text: item.text}))
            : source.text ? [{label: 'Texto', text: source.text}] : [];
        if (!units.length) {
          addTextElement(body, 'p', 'O texto do artigo não ficou disponível: a leitura foi indireta (pelo link). Envie o PDF para ver e conferir o texto integral.');
          previewDialog.showModal(); return;
        }
        addTextElement(body, 'p', `${units.length} ${source.pages?.length ? 'página(s)' : 'seção(ões)'} lidas. Destaque amarelo = trechos de origem das alegações.`, 'article-meta');
        const nav = document.createElement('div'); nav.className = 'page-nav';
        const select = document.createElement('select'); select.setAttribute('aria-label', 'Escolher página ou seção');
        units.forEach((unit, index) => { const option = document.createElement('option'); option.value = index; option.textContent = unit.label; select.appendChild(option); });
        nav.appendChild(select); body.appendChild(nav);
        const textBox = document.createElement('div'); textBox.className = 'page-text'; body.appendChild(textBox);
        const show = index => { clearNode(textBox); appendHighlighted(textBox, units[index].text || '', quotes); textBox.scrollTop = 0; };
        select.addEventListener('change', () => show(Number(select.value)));
        const firstWithQuote = units.findIndex(unit => quotes.some(quote => quote && (unit.text || '').replace(/\s+/g, ' ').includes(quote.replace(/\s+/g, ' '))));
        select.value = String(Math.max(0, firstWithQuote)); show(Math.max(0, firstWithQuote));
        previewDialog.showModal();
      } catch (error) { showError(error.message || 'Erro inesperado.'); }
    }
    document.getElementById('open-source-preview').addEventListener('click', openSourcePreview);
    function renderComplementary(data) {
      const status = document.getElementById('complementary-status');
      const button = document.getElementById('complementary-search');
      const info = data.complementary || {};
      button.disabled = pipelineBusy || info.status === 'RUNNING';
      if (info.status === 'RUNNING') status.textContent = 'Pesquisa complementar em andamento… os novos estudos entram na tabela e na síntese quando terminar.';
      else if (info.status === 'DONE') status.textContent = `Pesquisa complementar concluída: ${info.candidate_count} candidato(s), ${info.added_count} estudo(s) novo(s) incluído(s), ${info.added_assessed_count} lido(s). Consultas: ${(info.queries || []).join(' · ')}`;
      else if (info.status === 'FAILED') status.textContent = `A pesquisa complementar falhou: ${info.message || 'erro desconhecido'}`;
      else status.textContent = '';
      const trials = document.getElementById('trial-registry'); clearNode(trials);
      const registry = data.trial_registry;
      if (registry && registry.status === 'OK') {
        addTextElement(trials, 'h3', `Ensaios registrados no ClinicalTrials.gov: ${registry.registered_count}`);
        addTextElement(trials, 'p', `${registry.with_results_count} com resultados publicados no registro e ${registry.without_results_count} sem resultados. ${registry.note}`, 'article-meta');
        const list = document.createElement('div'); list.className = 'trial-list';
        (registry.examples || []).forEach(item => {
          const row = document.createElement('div');
          previewLink(row, `${item.nct_id}`, item.url);
          row.appendChild(document.createTextNode(` — ${item.title || ''} (${[item.status, (item.phases || []).join('/'), item.enrollment ? `n=${item.enrollment}` : null, item.has_results ? 'com resultados' : 'sem resultados'].filter(Boolean).join(', ')})`));
          list.appendChild(row);
        });
        trials.appendChild(list);
      }
    }
    complementaryTimer = null;
    async function pollComplementary() {
      clearTimeout(complementaryTimer);
      const response = await fetch(`/api/v1/analyses/${activeAnalysisId}`);
      if (!response.ok) return;
      const job = await response.json();
      const claim = (job.result?.claim_analyses || []).find(item => item.claim_id === activeClaimId);
      const running = (claim?.result?.complementary || job.result?.complementary || {}).status === 'RUNNING';
      if (running) { renderComplementary(claim?.result || job.result); complementaryTimer = setTimeout(pollComplementary, 6000); }
      else { complementaryTimer = null; renderAnalysis(job.result, false); }
    }
    document.getElementById('complementary-search').addEventListener('click', async event => {
      const button = event.currentTarget; button.disabled = true;
      try {
        const response = await fetch(`/api/v1/analyses/${activeAnalysisId}/claims/${encodeURIComponent(activeClaimId)}/complementary-search`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || 'Não foi possível iniciar a pesquisa complementar.');
        renderAnalysis(payload.result, false);
      } catch (error) { button.disabled = false; showError(error.message || 'Erro inesperado.'); }
    });
    function renderReproducibility(data) {
      const list = document.getElementById('reproducibility'); clearNode(list);
      const info = data.reproducibility || {};
      if (!Object.keys(info).length) { addTextElement(list, 'li', 'Metadados de reprodução não registrados nesta execução.'); return; }
      addTextElement(list, 'li', `Executado em ${info.executed_at || '—'} · profundidade ${info.depth || '—'}`);
      addTextElement(list, 'li', `Modelo de evidência: ${info.evidence_model || '—'} · tradução: ${info.translation_model || '—'}`);
      addTextElement(list, 'li', `Parâmetros: ${JSON.stringify(info.parameters || {})}`);
      (info.queries || []).forEach(query => addTextElement(list, 'li', `Consulta: ${query}`));
    }
    function renderStructuredSearch(payload) {
      const panel = document.getElementById('structured-search');
      const status = document.getElementById('structured-search-status');
      const grid = document.getElementById('structured-search-grid');
      clearNode(grid);
      panel.style.display = payload ? 'block' : 'none';
      if (!payload) return;
      const generation = ++structuredSearchGeneration;
      status.textContent = payload.checked_at
        ? `Consulta executada em ${new Date(payload.checked_at).toLocaleString()}.`
        : 'Consulta executada.';
      const card = (title, records, emptyText, formatter) => {
        const node = document.createElement('article'); node.className = 'structured-search-card';
        addTextElement(node, 'h4', title);
        if (!records.length) addTextElement(node, 'p', emptyText, 'structured-search-empty');
        records.slice(0, 8).forEach(record => {
          const item = document.createElement('div'); item.className = 'structured-search-record';
          formatter(item, record); node.appendChild(item);
        });
        return node;
      };
      Promise.resolve().then(() => {
        if (generation !== structuredSearchGeneration) return;
        const entities = payload.entities || {};
        const records = [
          ['Entidades detectadas', [
            `Genes: ${(entities.genes || []).join(', ') || 'nenhum'}`,
            `Variantes: ${(entities.variants || []).join(', ') || 'nenhuma'}`
          ]],
          ['Registros NCBI Gene', payload.gene_records || []],
          ['Registros ClinVar', payload.clinvar_records || []]
        ];
        const geneRecords = (payload.gene_records || []).map(record => ({
          title: record.name || record.nomenclature_symbol || record.uid || 'Registro NCBI Gene',
          detail: [record.description, record.organism, record.uid ? `GeneID ${record.uid}` : null].filter(Boolean).join(' · '),
          url: record.uid ? `https://www.ncbi.nlm.nih.gov/gene/${encodeURIComponent(record.uid)}` : null
        }));
        const clinvarRecords = (payload.clinvar_records || []).map(record => ({
          title: record.title || record.accessionversion || record.uid || 'Registro ClinVar',
          detail: [record.clinical_significance, record.condition, record.review_status, record.uid ? `UID ${record.uid}` : null].filter(Boolean).join(' · '),
          url: record.uid ? `https://www.ncbi.nlm.nih.gov/clinvar/variation/${encodeURIComponent(record.uid)}/` : null
        }));
        const entityCard = document.createElement('article'); entityCard.className = 'structured-search-card';
        addTextElement(entityCard, 'h4', records[0][0]);
        records[0][1].forEach(item => addTextElement(entityCard, 'p', item));
        grid.appendChild(entityCard);
        const addRecordCard = (title, items, empty) => {
          const node = card(title, items, empty, (parent, item) => {
            addTextElement(parent, 'strong', item.title || 'Registro');
            if (item.detail) addTextElement(parent, 'span', item.detail, 'article-meta');
            const url = safeUrl(item.url);
            if (url) {
              const link = document.createElement('a'); link.href = url; link.target = '_blank';
              link.rel = 'noopener noreferrer'; link.textContent = ' Conferir no NCBI ↗'; parent.appendChild(link);
            }
          });
          grid.appendChild(node);
        };
        addRecordCard('Registros NCBI Gene', geneRecords, 'Nenhum registro Gene localizado para as entidades detectadas.');
        addRecordCard('Registros ClinVar', clinvarRecords, 'Nenhum registro ClinVar localizado para as entidades detectadas.');
        const failures = payload.failures || [];
        status.textContent = failures.length
          ? `${payload.checked_at ? `Consultado em ${new Date(payload.checked_at).toLocaleString()}. ` : ''}${failures.length} fonte(s) retornaram falha; veja os detalhes.`
          : `Consultado em ${payload.checked_at ? new Date(payload.checked_at).toLocaleString() : 'data não informada'}.`;
        failures.forEach(failure => addTextElement(grid, 'p', `${failure.source}: ${failure.reason}`, 'structured-search-empty'));
      }).catch(error => {
        if (generation !== structuredSearchGeneration) return;
        status.textContent = `Busca estruturada indisponível: ${error.message}`;
        addTextElement(grid, 'p', 'O restante da análise continua disponível com PubMed/PMC.', 'structured-search-empty');
      });
    }

    function renderResult(data, shouldScroll) {
      const weighted = data.weighted_evidence || {};
      activeArticles = data.articles || [];
      renderWeighted(weighted);
      renderEvidenceMap(weighted.rows || []);
      renderEvidenceTable(weighted.rows || []);
      window.renderReferenceComparison?.(data, {analysisId: activeAnalysisId, claimId: activeClaimId, busy: pipelineBusy});
      renderReproducibility(data);
      renderUpdates(data);
      renderComplementary(data);
      if ((data.complementary || {}).status === 'RUNNING' && !complementaryTimer) complementaryTimer = setTimeout(pollComplementary, 6000);
      const report = data.report || {};
      const verification = data.verification || {};
      const submitted = data.submitted_article || {};
      const narrative = data.user_summary || {
        headline: report.headline,
        summary: report.summary,
        claim: submitted.primary_claim,
        interpretation: 'A saída técnica não trouxe um resumo consolidado.',
        reading: {}, evidence_balance: {}, findings: [],
        caveats: report.limitations || [], next_action: 'Confira as fontes manualmente.'
      };
      renderStructuredSearch(data.structured_search);
      const extractedClaim = document.getElementById('extracted-claim');
      extractedClaim.textContent = narrative.claim ? `O artigo afirma: ${narrative.claim}` : '';
      extractedClaim.style.display = narrative.claim ? 'block' : 'none';
      const claimQuote = document.getElementById('claim-quote');
      const submittedLocation = submitted.primary_claim_section
        ? ` — seção ${submitted.primary_claim_section}${submitted.primary_claim_page ? `, página ${submitted.primary_claim_page}` : ' (fonte sem paginação)'}`
        : (submitted.primary_claim_page ? ` — página ${submitted.primary_claim_page}` : '');
      claimQuote.textContent = submitted.primary_claim_quote ? `Trecho original: “${submitted.primary_claim_quote}”${submittedLocation}` : '';
      claimQuote.style.display = submitted.primary_claim_quote ? 'block' : 'none';
      document.getElementById('headline').textContent = text(narrative.headline);
      document.getElementById('summary').textContent = text(narrative.summary);
      document.getElementById('interpretation').textContent = text(narrative.interpretation);
      document.getElementById('next-action').textContent = text(narrative.next_action);

      const reading = narrative.reading || {};
      document.getElementById('reading-summary').textContent = text(reading.summary);

      const trace = narrative.search_trace || {};
      document.getElementById('cross-candidates').textContent = trace.candidate_count || 0;
      document.getElementById('cross-evaluated').textContent = trace.evaluated_count || 0;
      document.getElementById('cross-accepted').textContent = trace.accepted_count || 0;
      document.getElementById('cross-assessed').textContent = trace.assessed_count || 0;
      const crossSources = document.getElementById('cross-sources'); clearNode(crossSources);
      if (!(trace.sources || []).length) addTextElement(crossSources, 'span', 'Nenhuma base registrou resultados nesta execução.', 'article-meta');
      (trace.sources || []).forEach(source => addTextElement(crossSources, 'span', source, 'chip'));
      const crossQueries = document.getElementById('cross-queries'); clearNode(crossQueries);
      if (!(trace.queries || []).length) addTextElement(crossQueries, 'li', 'Consultas não registradas.');
      (trace.queries || []).forEach((query, index) => {
        const strategy = (trace.strategies || [])[index] || {};
        const detail = strategy.explanation ? `${query} — ${strategy.explanation}` : query;
        addTextElement(crossQueries, 'li', detail);
      });

      const indicators = verification.indicators || {};
      const coverage = indicators.search_coverage || {};
      const compatibility = indicators.evidence_compatibility || {};
      document.getElementById('coverage-label').textContent = text(coverage.label);
      document.getElementById('coverage-detail').textContent = text(coverage.explanation);
      document.getElementById('compatibility-label').textContent = text(compatibility.label);
      document.getElementById('compatibility-detail').textContent = text(compatibility.explanation);
      document.getElementById('methodology-label').textContent = 'Informações com origem rastreável';
      document.getElementById('methodology-detail').textContent = 'Metadados da API e trechos do texto são apresentados com sua origem. Campos sem respaldo são omitidos; a cobertura da leitura permanece indicada.';

      const dossier = data.article_dossier || {};
      const dossierPanel = document.getElementById('article-dossier');
      const dossierItems = document.getElementById('dossier-items'); clearNode(dossierItems);
      dossierPanel.style.display = Object.keys(dossier).length ? 'block' : 'none';
      if (Object.keys(dossier).length) {
        const identity = dossier.identity || {};
        const publication = dossier.publication || {};
        const editorial = dossier.editorial_status || {};
        const dossierMethod = dossier.methodology || {};
        const transparency = dossier.transparency || {};
        const sample = dossierMethod.sample_size || {};
        const protocol = dossierMethod.protocol || {};
        const addDossierItem = (title, detail) => {
          const card = document.createElement('article'); card.className = 'finding';
          addTextElement(card, 'h3', title); addTextElement(card, 'p', detail); dossierItems.appendChild(card);
        };
        const fieldLabels = {title: 'Título', pmid: 'PMID', doi: 'DOI', authors: 'Autores', journal: 'Periódico', publication_date: 'Data de publicação', publication_types: 'Tipos de publicação'};
        Object.entries(dossier.structured_fields || {}).forEach(([field, origin]) => {
          const value = Array.isArray(origin.value) ? origin.value.join('; ') : origin.value;
          if (value) addDossierItem(fieldLabels[field] || field, `${value} · fonte: ${origin.source}, campo ${origin.field}`);
        });
        if (editorial.retraction === 'RETRACTED') addDossierItem('Sinal editorial nos metadados', editorial.retraction_explanation);
        if ((editorial.corrections || []).length) addDossierItem('Atualizações editoriais nos metadados', editorial.corrections.join('; '));
        if ((protocol.identifiers || []).length) addDossierItem('Identificadores mencionados no texto', protocol.identifiers.join('; '));
        const transparencyLabels = {funding: 'financiamento', conflicts_of_interest: 'conflitos de interesse', data_availability: 'disponibilidade de dados'};
        Object.entries(transparency).forEach(([field, signal]) => {
          if (signal.excerpt) addDossierItem(`Trecho sobre ${transparencyLabels[field] || field.replaceAll('_', ' ')}`, `${sectionLabel(signal.section)}: “${signal.excerpt}”`);
        });


      }

      const limitations = document.getElementById('limitations'); clearNode(limitations);
      (narrative.caveats || []).forEach(item => addTextElement(limitations, 'li', item));

      const partial = verification.partial_verification || {};
      const meta = verification.meta_analysis || {};
      const trials = verification.clinical_trials || {};
      const search = data.search || {};
      const reranking = search.reranking || {};
      const technicalParts = [
        `Processamento detalhado: ${partial.verified_count || 0} de ${partial.total_count || 0} documentos com evidência utilizável.`,
        `Busca ampliada: ${(search.query_expansion || []).length} estratégias; reranker manteve ${reranking.accepted_count || 0} de ${reranking.evaluated_count || 0} candidatos.`,
        `Meta-análises: ${text(meta.explanation)}.`,
        `Ensaios clínicos: ${text(trials.explanation)}.`
      ];
      document.getElementById('technical-coverage').textContent = technicalParts.join(' ');

      const alerts = document.getElementById('verification-alerts'); clearNode(alerts);
      const alertItems = verification.alerts || [];
      if (!alertItems.length) addTextElement(alerts, 'li', 'Nenhum alerta automático foi produzido.');
      alertItems.forEach(item => {
        const li = document.createElement('li'); li.className = 'alert-item';
        li.dataset.severity = item.severity || 'INFO';
        addTextElement(li, 'strong', item.title);
        addTextElement(li, 'span', item.detail);
        const url = safeUrl(item.source_url);
        if (url) { const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = ' Conferir fonte'; li.appendChild(link); }
        alerts.appendChild(li);
      });

      const findings = document.getElementById('findings'); clearNode(findings);
      if (!(narrative.findings || []).length) {
        addTextElement(findings, 'p', 'Nenhum trecho independente pôde ser citado com segurança nesta execução.');
      }
      (narrative.findings || []).forEach(item => {
        const card = document.createElement('article'); card.className = 'finding';
        card.dataset.relation = item.relation || 'UNCERTAIN';
        card.classList.add('evidence-message');
        const heading = document.createElement('header'); heading.className = 'comparison-heading';
        const relationNames = {SUPPORTS: 'Compatível com a alegação', CONTRADICTS: 'Divergente da alegação', NEUTRAL: 'Contexto, sem resposta direta', UNCERTAIN: 'Comparação inconclusiva'};
        const title = document.createElement('h3'); title.textContent = relationNames[item.relation] || 'Comparação inconclusiva';
        heading.appendChild(title);
        addTextElement(heading, 'span', item.scope_label || 'Escopo não informado', 'comparison-scope');
        card.appendChild(heading);
        const comparison = document.createElement('div'); comparison.className = 'comparison-pair';
        const claimPanel = document.createElement('section'); claimPanel.className = 'comparison-claim';
        addTextElement(claimPanel, 'h4', 'Alegação investigada');
        addTextElement(claimPanel, 'p', item.compared_claim || narrative.claim || data.input?.claim || data.submitted_article?.primary_claim || 'A alegação não está registrada neste resultado.', 'comparison-claim-text');
        const evidencePanel = document.createElement('section'); evidencePanel.className = 'comparison-evidence';
        addTextElement(evidencePanel, 'h4', 'Trecho usado na comparação');
        if (item.quote) {
          if (item.quote_pt && item.quote_pt !== item.quote) {
            addTextElement(evidencePanel, 'span', 'Tradução para leitura', 'comparison-quote-label');
            addTextElement(evidencePanel, 'blockquote', item.quote_pt, 'translated');
            const original = document.createElement('details'); original.className = 'comparison-original';
            addTextElement(original, 'summary', 'Ver trecho literal no idioma original');
            addTextElement(original, 'blockquote', item.quote);
            evidencePanel.appendChild(original);
          } else {
            addTextElement(evidencePanel, 'span', 'Trecho literal do artigo', 'comparison-quote-label');
            addTextElement(evidencePanel, 'blockquote', item.quote);
          }
        } else addTextElement(evidencePanel, 'p', 'Não foi fornecido um trecho literal para conferir esta classificação.', 'missing-quote');
        if (item.location) addTextElement(evidencePanel, 'p', item.location, 'comparison-location');
        comparison.append(claimPanel, evidencePanel); card.appendChild(comparison);
        const explanation = document.createElement('section'); explanation.className = 'comparison-explanation';
        addTextElement(explanation, 'h4', 'Por que esta classificação?');
        addTextElement(explanation, 'p', item.rationale || 'A justificativa da classificação não foi registrada. Confira o trecho e a alegação antes de interpretar o resultado.');
        addTextElement(explanation, 'small', 'Esta classificação indica uma relação textual; não confirma a alegação nem avalia a qualidade do estudo.');
        card.appendChild(explanation);
        const source = document.createElement('section'); source.className = 'comparison-source';
        addTextElement(source, 'h4', 'Artigo consultado');
        addTextElement(source, 'p', item.article_title_pt || item.article_title, 'comparison-source-title');
        const studyMeta = [item.journal, item.publication_date ? formatPublicationDate(item.publication_date) : null, item.pmid ? `PMID ${item.pmid}` : null].filter(Boolean).join(' · ');
        if (studyMeta) addTextElement(source, 'p', studyMeta, 'article-meta');
        card.appendChild(source);
        const details = document.createElement('details'); details.className = 'comparison-details';
        addTextElement(details, 'summary', 'Detalhes do achado e da busca');
        if (item.article_title_pt && item.article_title_pt !== item.article_title) {
          addTextElement(details, 'h4', 'Título original'); addTextElement(details, 'p', item.article_title);
        }
        if (item.finding_pt) {
          addTextElement(details, 'h4', 'Resumo automático do achado'); addTextElement(details, 'p', item.finding_pt);
        }
        const discovery = (item.retrieval_sources || []).join(', ');
        const relevance = (item.relevance_reasons || []).join('; ');
        if (discovery) { addTextElement(details, 'h4', 'Onde o artigo foi encontrado'); addTextElement(details, 'p', discovery); }
        if (relevance) { addTextElement(details, 'h4', 'Por que foi selecionado na busca'); addTextElement(details, 'p', relevance); }
        if (item.model_name) { addTextElement(details, 'h4', 'Modelo da comparação'); addTextElement(details, 'p', item.model_name); }
        if (item.doi) addTextElement(details, 'p', `DOI: ${item.doi}`, 'article-meta');
        card.appendChild(details);
        const actions = document.createElement('div'); actions.className = 'message-actions';
        if (item.quote) {
          const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'secondary copy-evidence';
          copy.dataset.copyText = [item.article_title || item.article_title_pt, item.quote, item.location, safeUrl(item.source_url)].filter(Boolean).join('\n\n');
          copy.textContent = 'Copiar trecho e fonte'; actions.appendChild(copy);
        }
        const url = safeUrl(item.source_url);
        if (url) { const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = 'Conferir no artigo ↗'; actions.appendChild(link); }
        card.appendChild(actions);
        findings.appendChild(card);
      });

      const sources = document.getElementById('sources'); clearNode(sources);
      (report.sources || []).forEach(source => {
        const li = document.createElement('li'); const url = safeUrl(source.url);
        if (url) { const link = document.createElement('a'); link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; link.textContent = text(source.label); li.appendChild(link); }
        else { li.textContent = text(source.label); }
        sources.appendChild(li);
      });
      statusBox.style.display = pipelineBusy ? 'block' : 'none'; claimReview.style.display = 'block';
      resultBox.style.display = 'block'; submit.disabled = false; researchSelected.disabled = pipelineBusy;
      if (shouldScroll !== false) resultBox.scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    function renderAnalysis(data, shouldScroll) {
      setWorkflowStep(3);
      if (activeAnalysisId) loadArticleReader({analysis_id: activeAnalysisId, status: pipelineBusy ? 'RESEARCHING' : 'SUCCEEDED', result: data});
      renderWholeArticle(data.whole_article_analysis);
      document.getElementById('watch-toggle').checked = Boolean(data.watch?.enabled);
      document.getElementById('watch-toggle').disabled = pipelineBusy;
      document.getElementById('export-markdown').href = activeAnalysisId ? `/api/v1/analyses/${activeAnalysisId}/report.md` : '#';
      const navigation = document.getElementById('claim-navigation');
      const tabs = document.getElementById('claim-tabs'); clearNode(tabs);
      const analyses = (data.claim_analyses || []).filter(item => item.status === 'SUCCEEDED' && item.result);
      if (!analyses.length) {
        navigation.style.display = 'none';
        activeClaimId = null;
        renderResult(data, shouldScroll !== false);
        return;
      }
      navigation.style.display = 'block';
      const statusLabels = {
        MIXED: 'Estudos em direções diferentes',
        PREDOMINANTLY_COMPATIBLE: 'Compatibilidade preliminar',
        POTENTIAL_DIVERGENCE: 'Divergência encontrada',
        NO_DIRECT_COMPARISON: 'Sem comparação direta'
      };
      const informativeness = analysis => {
        const summary = analysis.result.user_summary || {};
        const balance = summary.evidence_balance || {};
        const direct = (balance.SUPPORTS || 0) + (balance.CONTRADICTS || 0);
        const assessed = summary.reading?.assessed_count || 0;
        const statusWeight = {MIXED: 40, POTENTIAL_DIVERGENCE: 35, PREDOMINANTLY_COMPATIBLE: 30, NO_DIRECT_COMPARISON: 0};
        return (statusWeight[summary.status] || 0) + direct * 5 + assessed;
      };
      const keptIndex = analyses.findIndex(item => item.claim_id === activeClaimId);
      const initialIndex = keptIndex >= 0 ? keptIndex : analyses.reduce((best, item, index) =>
        informativeness(item) > informativeness(analyses[best]) ? index : best, 0);
      const selectAnalysis = (index, shouldScroll) => {
        tabs.querySelectorAll('.claim-tab').forEach((item, itemIndex) =>
          item.setAttribute('aria-selected', itemIndex === index ? 'true' : 'false'));
        activeClaimId = analyses[index].claim_id;
        document.querySelectorAll('#claim-pipeline-tabs .claim-tab').forEach(tab =>
          tab.setAttribute('aria-current', String(tab.dataset.claimId === activeClaimId)));
        renderResult(analyses[index].result, shouldScroll);
      };
      analyses.forEach((analysis, index) => {
        const summary = analysis.result.user_summary || {};
        const balance = summary.evidence_balance || {};
        const direct = (balance.SUPPORTS || 0) + (balance.CONTRADICTS || 0);
        const assessed = summary.reading?.assessed_count || 0;
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'claim-tab'; button.setAttribute('role', 'tab');
        button.setAttribute('aria-selected', index === initialIndex ? 'true' : 'false');
        addTextElement(button, 'span', `Alegação ${index + 1}`, 'claim-number');
        addTextElement(button, 'span', analysis.claim?.text || analysis.claim_id, 'claim-text');
        const verdict = analysis.result.weighted_evidence?.verdict;
        addTextElement(button, 'span', verdict ? `${verdict.label}${verdict.certainty_label ? ` · certeza ${verdict.certainty_label.toLowerCase()}` : ''}` : (statusLabels[summary.status] || summary.headline || 'Resultado disponível'), 'claim-outcome');
        addTextElement(button, 'span', `${assessed} estudo(s) analisado(s) · ${direct} comparação(ões) direta(s)`, 'claim-metrics');
        button.addEventListener('click', () => selectAnalysis(index, false));
        tabs.appendChild(button);
      });
      activeClaimId = analyses[initialIndex].claim_id;
      renderResult(analyses[initialIndex].result, shouldScroll !== false);
    }
    const formatMinutes = seconds => seconds < 90 ? `${Math.round(seconds)} s` : `${Math.round(seconds / 60)} min`;
    function selectedDepth() { return document.querySelector('input[name="depth"]:checked')?.value || 'QUICK'; }
    function updateEstimate() {
      const count = reviewClaims.querySelectorAll('input[type="checkbox"]:checked').length;
      selectionCount.textContent = `${count} alegação(ões) selecionada(s)`;
      reviewClaims.querySelectorAll('.claim-card').forEach(card => { card.dataset.checked = card.querySelector('input[type="checkbox"]').checked ? 'true' : 'false'; });
      const box = document.getElementById('research-estimate');
      const modes = activeEstimates?.modes || {};
      ['QUICK', 'DEEP'].forEach(code => {
        const mode = modes[code]; const node = document.getElementById(code === 'QUICK' ? 'depth-quick-detail' : 'depth-deep-detail');
        node.textContent = mode ? ` ${mode.description}` : '';
      });
      const mode = modes[selectedDepth()];
      if (!mode || !count) { box.textContent = count ? '' : 'Selecione ao menos uma alegação para ver a estimativa.'; return; }
      const [low, high] = mode.seconds_per_claim;
      const cost = mode.cost_usd_per_claim * count;
      box.textContent = `Estimativa para ${count} alegação(ões): ${formatMinutes(low * count)} a ${formatMinutes(high * count)}, cerca de ${(mode.tokens_per_claim * count).toLocaleString('pt-BR')} tokens do Gemini (≈ US$ ${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}). ${activeEstimates.pricing_basis || ''}`;
    }
    async function startResearch(selected) {
      try {
        if (!selected.length) throw new Error('Selecione ao menos uma alegação.');
        researchSelected.disabled = true; errorBox.style.display = 'none';
        reviewClaims.querySelectorAll('button').forEach(item => { item.disabled = true; });
        const response = await fetch(activeSelectionUrl, {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({claims: selected, depth: selectedDepth(), comparison: await window.getComparisonSelection()})
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || 'Não foi possível iniciar a investigação.');
        pipelineBusy = true; claimReview.style.display = 'block'; statusBox.style.display = 'block';
        await poll(payload.status_url || activeStatusUrl);
      } catch (error) {
        researchSelected.disabled = false;
        reviewClaims.querySelectorAll('button').forEach(item => { item.disabled = false; });
        showError(error.message || 'Erro inesperado.');
      }
    }
    function renderClaimSelection(job, shouldScroll = true) {
      pipelineBusy = job.status === 'RESEARCHING';
      researchSelected.disabled = pipelineBusy;
      window.restoreComparisonSelection?.(job.result?.comparison);
      setWorkflowStep(2);
      const completedById = new Map((job.result?.claim_analyses || []).map(item => [item.claim_id, item]));
      const claims = (job.result?.submitted_article?.claims || []).map(claim => ({...claim, ...(completedById.get(claim.claim_id)?.claim || {})}));
      activeEstimates = job.result?.research_estimates || null;
      clearNode(reviewClaims);
      if (!claims.length) throw new Error('Nenhuma alegação editável foi extraída do artigo.');
      const importanceLabels = {HIGH: 'Importância alta', MEDIUM: 'Importância média', LOW: 'Importância baixa'};
      claims.forEach((claim, index) => {
        const profile = claim.profile || {};
        const card = document.createElement('article'); card.className = 'claim-card';
        card.dataset.claimId = claim.claim_id;
        card.dataset.userSupplied = claim.user_supplied ? 'true' : 'false';
        const head = document.createElement('div'); head.className = 'claim-card-head';
        const toggle = document.createElement('label');
        const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.dataset.claimId = claim.claim_id;
        checkbox.checked = !completedById.has(claim.claim_id);
        checkbox.disabled = pipelineBusy;
        checkbox.addEventListener('change', updateEstimate);
        toggle.appendChild(checkbox); addTextElement(toggle, 'strong', `Alegação ${index + 1}`); head.appendChild(toggle);
        if (profile.claim_type_label) addTextElement(head, 'span', profile.claim_type_label, 'badge');
        if (profile.importance) { const badge = addTextElement(head, 'span', importanceLabels[profile.importance] || profile.importance, 'badge'); badge.dataset.level = profile.importance; if (profile.importance_reason) badge.title = profile.importance_reason; }
        const entry = completedById.get(claim.claim_id);
        addTextElement(head, 'span', ({SUCCEEDED: 'Comparação pronta', RUNNING: 'Comparando…', QUEUED: 'Na fila', FAILED: 'Falhou; pode tentar novamente'})[entry?.status] || 'Ainda não investigada', 'badge');
        if (entry?.error?.message) addTextElement(card, 'p', entry.error.message);
        card.appendChild(head);
        const editor = document.createElement('textarea'); editor.value = claim.text || '';
        editor.disabled = pipelineBusy;
        editor.maxLength = 2000; editor.dataset.claimId = claim.claim_id; editor.setAttribute('aria-label', `Texto da alegação ${index + 1}`);
        card.appendChild(editor);
        const editedNote = addTextElement(card, 'div', 'Texto alterado: tipo, PICO e consultas serão refeitos antes da busca.', 'edited-note');
        editedNote.style.display = 'none';
        editor.addEventListener('input', () => { editedNote.style.display = editor.value.trim() !== (claim.text || '') ? 'block' : 'none'; });
        const location = [sectionLabel(claim.section), claim.page ? `p. ${claim.page}` : null].filter(Boolean).join(', ');
        if (claim.quote) addTextElement(card, 'div', `Trecho de origem: “${claim.quote}”${location ? ` — ${location}` : ''}`, 'review-source');
        else addTextElement(card, 'div', claim.user_supplied ? 'Alegação adicionada por você; não atribuída automaticamente aos autores.' : 'Trecho literal de origem não localizado no texto extraído.', 'review-source');
        if (claim.profile) {
          const pico = document.createElement('div'); pico.className = 'pico-grid';
          [['População', profile.population], ['Intervenção/exposição', profile.intervention], ['Comparador', profile.comparator], ['Desfecho', profile.outcome]].forEach(([label, value]) => {
            const field = document.createElement('div'); field.className = 'study-field';
            addTextElement(field, 'strong', label); addTextElement(field, 'span', value || 'Não especificado'); pico.appendChild(field);
          });
          card.appendChild(pico);
          if (profile.importance_reason) addTextElement(card, 'div', `Por que importa: ${profile.importance_reason}`, 'review-source');
        }
        const actions = document.createElement('div'); actions.className = 'actions'; actions.style.marginTop = '4px';
        const single = document.createElement('button'); single.type = 'button'; single.className = 'secondary';
        single.textContent = entry?.status === 'SUCCEEDED' ? 'Comparar novamente' : 'Investigar esta alegação';
        single.disabled = pipelineBusy;
        single.addEventListener('click', () => startResearch([{claim_id: claim.claim_id, text: editor.value.trim(), ...(claim.user_supplied ? {source:'USER'} : {})}]));
        actions.appendChild(single);
        if (entry?.status === 'SUCCEEDED' && entry.result) {
          const view = document.createElement('button'); view.type = 'button'; view.className = 'secondary'; view.textContent = 'Ver comparação';
          view.addEventListener('click', () => { activeClaimId = claim.claim_id; renderAnalysis(job.result, false); resultBox.scrollIntoView({behavior:'smooth'}); });
          actions.appendChild(view);
        }
        card.appendChild(actions);
        reviewClaims.appendChild(card);
      });
      document.querySelectorAll('input[name="depth"]').forEach(item => { item.onchange = updateEstimate; });
      updateEstimate();
      activeAnalysisId = job.analysis_id;
      renderWholeArticle(job.result?.whole_article_analysis);
      activeStatusUrl = `/api/v1/analyses/${job.analysis_id}`;
      activeSelectionUrl = job.claim_selection_url || `/api/v1/article-analyses/${job.analysis_id}/claims`;
      loadArticleReader(job);
      statusBox.style.display = pipelineBusy ? 'block' : 'none';
      if (job.status === 'AWAITING_CLAIM_SELECTION') resultBox.style.display = 'none';
      claimReview.style.display = 'block'; submit.disabled = false;
      renderPipelineNavigation(job);
      if (shouldScroll) document.getElementById('source-reader').scrollIntoView({behavior: 'smooth', block: 'start'});
    }
    researchSelected.addEventListener('click', () => {
      const selected = [];
      reviewClaims.querySelectorAll('.claim-card').forEach(card => {
        const checkbox = card.querySelector('input[type="checkbox"]');
        if (checkbox.checked) selected.push({claim_id: checkbox.dataset.claimId, text: card.querySelector('textarea').value.trim(), ...(card.dataset.userSupplied === 'true' ? {source:'USER'} : {})});
      });
      startResearch(selected);
    });
    document.getElementById('export-pdf').addEventListener('click', () => window.print());
    window.addEventListener('beforeprint', () => document.querySelectorAll('details').forEach(item => { item.dataset.wasOpen = item.open ? 'true' : 'false'; item.open = true; }));
    window.addEventListener('afterprint', () => document.querySelectorAll('details').forEach(item => { item.open = item.dataset.wasOpen === 'true'; }));
    function renderPipelineNavigation(job) {
      const panel = document.getElementById('claim-pipeline'); panel.hidden = false;
      const tabs = document.getElementById('claim-pipeline-tabs'); clearNode(tabs);
      const entries = new Map((job.result?.claim_analyses || []).map(item => [item.claim_id, item]));
      (job.result?.submitted_article?.claims || []).forEach((claim, index) => {
        const entry = entries.get(claim.claim_id);
        const button = document.createElement('button'); button.type = 'button'; button.className = 'claim-tab';
        button.dataset.claimId = claim.claim_id;
        button.dataset.status = entry?.status || 'UNSELECTED';
        button.setAttribute('aria-current', String(activeClaimId === claim.claim_id));
        addTextElement(button, 'span', `Alegação ${index + 1}`, 'claim-number');
        addTextElement(button, 'span', entry?.claim?.text || claim.text, 'claim-text');
        addTextElement(button, 'span', ({SUCCEEDED:'Pronta', RUNNING:'Comparando…', QUEUED:'Na fila', FAILED:'Falhou'})[entry?.status] || 'Selecionar para investigar', 'claim-outcome');
        button.addEventListener('click', () => {
          activeClaimId = claim.claim_id;
          tabs.querySelectorAll('button').forEach(tab => tab.setAttribute('aria-current', String(tab === button)));
          if (entry?.status === 'SUCCEEDED' && entry.result) { renderAnalysis(job.result, false); resultBox.scrollIntoView({behavior:'smooth'}); }
          else { const editor = [...reviewClaims.querySelectorAll('textarea')].find(node => node.dataset.claimId === claim.claim_id); editor?.scrollIntoView({behavior:'smooth', block:'center'}); editor?.focus(); }
        });
        tabs.appendChild(button);
      });
    }
    document.getElementById('add-custom-claim').addEventListener('click', () => {
      if (pipelineBusy) return;
      const id = 'user-' + crypto.randomUUID();
      const card = document.createElement('article'); card.className = 'claim-card'; card.dataset.claimId = id; card.dataset.userSupplied = 'true';
      const label = document.createElement('label'); const checkbox = document.createElement('input'); checkbox.type = 'checkbox'; checkbox.checked = true; checkbox.dataset.claimId = id; checkbox.addEventListener('change', updateEstimate);
      label.appendChild(checkbox); addTextElement(label, 'strong', 'Sua alegação'); card.appendChild(label);
      const editor = document.createElement('textarea'); editor.dataset.claimId = id; editor.maxLength = 2000; editor.setAttribute('aria-label', 'Sua alegação'); card.appendChild(editor);
      addTextElement(card, 'p', 'Adicionada por você; não atribuída automaticamente aos autores.', 'review-source');
      const single = document.createElement('button'); single.type = 'button'; single.className = 'secondary'; single.textContent = 'Investigar esta alegação'; single.addEventListener('click', () => startResearch([{claim_id:id, text:editor.value.trim(), source:'USER'}])); card.appendChild(single);
      reviewClaims.appendChild(card); updateEstimate(); editor.focus();
    });
    ['select-all-claims', 'clear-claim-selection'].forEach((id, index) => document.getElementById(id).addEventListener('click', () => {
      if (pipelineBusy) return;
      reviewClaims.querySelectorAll('input[type="checkbox"]').forEach(node => { node.checked = index === 0; }); updateEstimate();
    }));
    async function poll(statusUrl) {
      const generation = ++pollGeneration;
      let previousProgress = '';
      for (;;) {
        const response = await fetch(`${statusUrl}?view=status`, {headers: {'Accept': 'application/json'}});
        if (generation !== pollGeneration) return;
        if (!response.ok) throw new Error('Não foi possível consultar o andamento da análise.');
        const status = await response.json(); setProgress(status.status, status.progress || 0);
        activeAnalysisId = status.analysis_id || activeAnalysisId;
        pipelineBusy = ['QUEUED','RUNNING','RESEARCHING'].includes(status.status);
        const signature = JSON.stringify(status.claim_progress || []);
        const terminal = ['SUCCEEDED','AWAITING_CLAIM_SELECTION','FAILED'].includes(status.status);
        if (terminal || (status.status === 'RESEARCHING' && signature !== previousProgress)) {
          previousProgress = signature;
          const full = await fetch(statusUrl, {headers: {'Accept': 'application/json'}});
          if (generation !== pollGeneration) return;
          if (!full.ok) throw new Error('Não foi possível carregar o resultado da análise.');
          const job = await full.json();
          if (job.result?.submitted_article?.claims?.length) {
            renderClaimSelection(job, terminal);
            if ((job.result.claim_analyses || []).some(item => item.status === 'SUCCEEDED' && item.result)) renderAnalysis(job.result, false);
          }
          if (terminal) {
            if (job.status === 'FAILED') showError(job.error?.message || 'A análise falhou.');
            window.refreshArticleLibrary?.();
            return;
          }
        }
        await new Promise(resolve => setTimeout(resolve, 1500));
      }
    }
    window.openAnalysisSession = async analysisId => {
      activeAnalysisId = analysisId; activeClaimId = null;
      activeStatusUrl = `/api/v1/analyses/${encodeURIComponent(analysisId)}`;
      activeSelectionUrl = `/api/v1/article-analyses/${encodeURIComponent(analysisId)}/claims`;
      resetArticleReader(); await poll(activeStatusUrl);
    };
    async function runTopicSearch(page = 1) {
      const button = document.getElementById('topic-submit');
      const status = document.getElementById('topic-status');
      const results = document.getElementById('topic-results');
      const clusterResults = document.getElementById('topic-cluster-results');
      if (page === 1) {
        window.cancelPubmedClusters?.();
        clearNode(clusterResults);
      }
      button.disabled = true; clearNode(results);
      status.classList.add('is-loading');
      document.getElementById('topic-form').setAttribute('aria-busy', 'true');
      status.textContent = 'Preparando a consulta e pesquisando no PubMed…';
      try {
        if (page === 1) { activeTopicQuery = null; activeTopicMode = null; }
        const requestBody = {
          topic: document.getElementById('topic-input').value.trim(),
          article_type: document.getElementById('topic-type').value,
          availability: document.getElementById('topic-availability').value,
          indexing: document.getElementById('topic-indexing').value,
          language: document.getElementById('topic-language').value,
          page,
          page_size: Number(document.getElementById('topic-page-size').value)
        };
        if (page > 1 && activeTopicQuery) requestBody.prepared_query = activeTopicQuery;
        const response = await fetch('/api/v1/pubmed-search', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(requestBody)
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error?.message || 'Não foi possível pesquisar.');
        const articles = data.articles || [];
        const pagination = data.pagination || {};
        if (page === 1) {
          activeTopicQuery = data.query_results?.[0]?.query || null;
          activeTopicMode = data.mode;
        }
        const mode = activeTopicMode === 'ASSISTED' ? 'Termos organizados com IA.' : 'Consulta direta ao PubMed, sem expansão por IA.';
        status.textContent = articles.length
          ? `Exibindo ${pagination.first_result}–${pagination.last_result} de ${pagination.total_results} artigos. ${mode} ${data.limitation || ''}${pagination.limited_by_pubmed ? ' O PubMed limita a navegação desta consulta aos primeiros 10.000 resultados; refine os termos para acessar os demais.' : ''}`
          : `Nenhum artigo encontrado. Tente outros termos ou amplie os filtros. ${mode}`;
        if (articles.length) {
          const resultHeader = document.createElement('div'); resultHeader.className = 'topic-result-header';
          addTextElement(resultHeader, 'strong', `${pagination.total_results} resultados no PubMed`);
          addTextElement(resultHeader, 'span', `Página ${pagination.page} de ${pagination.total_pages}`);
          results.appendChild(resultHeader);
        }
        const queries = document.createElement('details');
        queries.className = 'topic-query-details';
        addTextElement(queries, 'summary', 'Ver consultas usadas');
        (data.query_results || []).forEach(item => addTextElement(queries, 'p', `${item.query} — ${item.status === 'OK' ? `${item.total_matches} resultado(s) no PubMed` : 'consulta indisponível'}`));
        articles.forEach(article => {
          const card = document.createElement('article'); card.className = 'finding topic-card';
          card.dataset.pmid = article.pmid;
          addTextElement(card, 'h3', article.title_pt || article.title);
          if (article.title_pt && article.title_pt !== article.title) {
            addTextElement(card, 'p', `Título original: ${article.title}`, 'article-original-title');
          }
          const availability = article.has_full_text ? 'Texto completo no PMC' : 'Registro no PubMed';
          const indexing = article.is_medline ? 'Indexado no MEDLINE' : 'Não confirmado no MEDLINE';
          addTextElement(card, 'p', [article.journal, formatPublicationDate(article.publication_date), `PMID ${article.pmid}`, ...(article.language_labels || []), indexing, availability, ...(article.publication_type_labels || [])].filter(Boolean).join(' · '), 'article-meta');
          if (article.authors?.length) addTextElement(card, 'p', article.authors.slice(0, 3).join(', '), 'article-meta');
          previewLink(card, 'Abrir no PubMed', article.url);
          if (article.pmc_url) {
            const separator = document.createTextNode(' · '); card.appendChild(separator);
            previewLink(card, 'Ler texto completo no PMC', article.pmc_url);
          }
          const choose = document.createElement('button'); choose.type = 'button'; choose.className = 'secondary';
          choose.textContent = 'Usar este artigo'; choose.style.marginLeft = '12px';
          choose.addEventListener('click', () => {
            setInputMode('link');
            document.getElementById('article-file').value = '';
            const reference = document.getElementById('article-reference');
            reference.value = article.url;
            document.getElementById('analysis-form').scrollIntoView({behavior: 'smooth', block: 'center'});
            reference.focus({preventScroll: true});
            status.textContent = 'Artigo selecionado. Continue na aba de referência para iniciar a leitura.';
          });
          card.appendChild(choose); results.appendChild(card);
        });
        if (articles.length) {
          const navigation = document.createElement('nav'); navigation.className = 'topic-pagination'; navigation.setAttribute('aria-label', 'Páginas dos resultados');
          const previous = document.createElement('button'); previous.type = 'button'; previous.className = 'secondary'; previous.textContent = '← Página anterior'; previous.disabled = !pagination.has_previous;
          previous.addEventListener('click', () => runTopicSearch(pagination.page - 1));
          const pageLabel = document.createElement('span'); pageLabel.textContent = `Página ${pagination.page} de ${pagination.total_pages}`;
          const next = document.createElement('button'); next.type = 'button'; next.className = 'secondary'; next.textContent = 'Próxima página →'; next.disabled = !pagination.has_next;
          next.addEventListener('click', () => runTopicSearch(pagination.page + 1));
          navigation.append(previous, pageLabel, next); results.appendChild(navigation);
        }
        results.appendChild(queries);
        if (page === 1 && articles.length && document.getElementById('topic-clusters-enabled').checked) {
          window.showPubmedClusters?.(articles, clusterResults, {enrich: true, cardsRoot: results});
        }
        if (page > 1) results.scrollIntoView({behavior: 'smooth', block: 'start'});
      } catch (error) {
        status.textContent = error.message || 'Erro ao consultar o PubMed.';
      } finally {
        status.classList.remove('is-loading');
        document.getElementById('topic-form').setAttribute('aria-busy', 'false');
        button.disabled = false;
      }
    }
    document.getElementById('topic-form').addEventListener('submit', event => {
      event.preventDefault();
      runTopicSearch(1);
    });

    form.addEventListener('submit', async event => {
      event.preventDefault(); submit.disabled = true; errorBox.style.display = 'none';
      activeClaimId = null; activeAnalysisId = null; pollGeneration++;
      pipelineBusy = false; document.getElementById('claim-pipeline').hidden = true;
      resetArticleReader();
      resultBox.style.display = 'none'; claimReview.style.display = 'none';
      document.getElementById('whole-article-report').style.display = 'none';
      researchSelected.disabled = false; statusBox.style.display = 'block'; setProgress('QUEUED', 0);
      const reference = document.getElementById('article-reference').value.trim();
      const file = document.getElementById('article-file').files[0];
      try {
        if ((!reference && !file) || (reference && file)) {
          throw new Error('Informe exatamente uma origem: link/DOI ou arquivo.');
        }
        if (file && file.size > 25 * 1024 * 1024) {
          throw new Error('O arquivo deve ter no máximo 25 MB.');
        }
        const body = {article_reference: reference || null};
        if (file) {
          const bytes = new Uint8Array(await file.arrayBuffer());
          let binary = ''; const block = 0x8000;
          for (let index = 0; index < bytes.length; index += block) {
            binary += String.fromCharCode(...bytes.subarray(index, index + block));
          }
          body.article_reference = null;
          body.article_file = {name: file.name, mime_type: file.type, data_base64: btoa(binary)};
        }
        const response = await fetch('/api/v1/article-analyses', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(body)
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error?.message || 'Não foi possível iniciar a análise.');
        await poll(payload.status_url);
      } catch (error) { showError(error.message || 'Erro inesperado.'); }
    });
  </script>
  <script src="/static/topic-clusters.js"></script>
  <script src="/static/reference-comparison.js"></script>
  <script src="/static/workspace.js"></script>
  <script src="/static/article-reader.js"></script>
  <script src="/static/library.js"></script>
  <script src="/static/interactions.js"></script>
  <script src="/static/screen-ui.js"></script>
</body>
</html>"""


def register_web_ui(
    app: Flask,
    *,
    mode_label: str = "PROTÓTIPO LOCAL — resultados dependem do backend configurado",
) -> None:
    """Registra a página sem acoplar a interface ao pipeline científico."""

    rendered = WEB_UI_HTML.replace("__MODE_LABEL__", escape(mode_label))

    @app.get("/")
    def index() -> Response:
        return Response(rendered, mimetype="text/html")
