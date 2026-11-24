# -*- coding: utf-8 -*-
"""报告增强用的静态 CSS / JS 资源。

从 report_enhancer.py 拆出，避免渲染逻辑与样式字符串混在一个文件里。
修改样式只需改这里，增强器通过 import 注入，报告仍是单文件自包含。
"""

CSS = """
<style id="enh-style">
.enh-root{--enh-border:#e6e8ef;--enh-muted:#6b7280;--enh-dark:#111827;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  color:var(--enh-dark);margin:0 0 22px;padding:24px 26px;background:#f7f8fc;border-bottom:1px solid var(--enh-border)}
.enh-hero{display:flex;align-items:center;justify-content:space-between;gap:24px;margin-bottom:20px}
.enh-eyebrow{font-size:11px;letter-spacing:.18em;color:#6366f1;font-weight:700;margin-bottom:6px}
.enh-hero h1{font-size:26px;margin:0 0 6px;color:#111827;font-weight:700}
.enh-hero-sub{font-size:12px;color:var(--enh-muted)}
.enh-rate{width:112px;height:112px;border-radius:50%;flex:0 0 auto;
  background:conic-gradient(#22c55e calc(var(--rate)*1%),#e8eaf1 0);
  display:grid;place-items:center;box-shadow:0 6px 20px rgba(34,197,94,.15)}
.enh-rate-inner{width:86px;height:86px;border-radius:50%;background:#fff;display:flex;
  flex-direction:column;align-items:center;justify-content:center}
.enh-rate-inner b{font-size:24px;line-height:1;color:#15803d}
.enh-rate-inner span{font-size:11px;color:var(--enh-muted);margin-top:4px}
.enh-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:16px}
.enh-kpi{background:#fff;border:1px solid var(--enh-border);border-radius:12px;padding:14px 16px;
  box-shadow:0 2px 8px rgba(17,24,39,.035);border-top:3px solid #94a3b8}
.enh-kpi-indigo{border-top-color:#6366f1}.enh-kpi-green{border-top-color:#22c55e}
.enh-kpi-red{border-top-color:#ef4444}.enh-kpi-amber{border-top-color:#f59e0b}
.enh-kpi-blue{border-top-color:#3b82f6}.enh-kpi-purple{border-top-color:#a855f7}
.enh-kpi-label{font-size:12px;color:var(--enh-muted)}
.enh-kpi-value{font-size:26px;font-weight:700;line-height:1.25;margin:2px 0;color:#111827}
.enh-kpi-sub{font-size:11px;color:#9ca3af}.enh-unit{font-size:14px;margin-left:2px;color:var(--enh-muted)}
.enh-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.enh-card{background:#fff;border:1px solid var(--enh-border);border-radius:12px;padding:16px 18px;min-width:0;
  box-shadow:0 2px 8px rgba(17,24,39,.035)}
.enh-card-wide{grid-column:1/-1}
.enh-card h3{font-size:14px;margin:0 0 12px;color:#1f2937;font-weight:700}
.enh-card h3 small{font-weight:400;color:#9ca3af;font-size:11px;margin-left:8px}
.enh-card h3.enh-gap{margin-top:18px}
.enh-bar-row{display:grid;grid-template-columns:130px minmax(0,1fr) 90px;align-items:center;gap:12px;margin:7px 0;font-size:12px}
.enh-bar-label{color:#374151;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.enh-bar-track{height:9px;background:#eef0f5;border-radius:6px;overflow:hidden}
.enh-bar-fill{height:100%;border-radius:6px;background:linear-gradient(90deg,#818cf8,#6366f1)}
.enh-bar-fail{background:linear-gradient(90deg,#f87171,#ef4444)}
.enh-bar-num{text-align:right;color:#111827;font-weight:600}.enh-bar-num span{color:#9ca3af;font-weight:400}
.enh-table{width:100%;border-collapse:collapse;font-size:11px;table-layout:fixed}
.enh-table th{text-align:left;color:#9ca3af;font-weight:600;padding:5px 4px;border-bottom:1px solid var(--enh-border)}
.enh-table td{padding:5px 4px;border-bottom:1px solid #f3f4f7;color:#374151}
.enh-table th:nth-child(1),.enh-table td:nth-child(1){width:56px}
.enh-table th:nth-child(3),.enh-table td:nth-child(3),.enh-table th:nth-child(4),.enh-table td:nth-child(4),
.enh-table th:nth-child(5),.enh-table td:nth-child(5),.enh-table th:nth-child(6),.enh-table td:nth-child(6){width:52px}
.enh-endpoint-path{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.enh-num{text-align:right;font-variant-numeric:tabular-nums}
.enh-status-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.enh-status-item{border-radius:10px;padding:12px;text-align:center;background:#f0fdf4}
.enh-status-item b{display:block;font-size:22px;color:#15803d}.enh-status-item span{font-size:11px;color:#6b7280}
.enh-status-item.s4{background:#fffbeb}.enh-status-item.s4 b{color:#b45309}
.enh-status-item.s5{background:#fef2f2}.enh-status-item.s5 b{color:#b91c1c}
.enh-sub-title{font-size:11px;font-weight:700;color:#6b7280;margin:12px 0 6px;letter-spacing:.02em}
.enh-status-codes{grid-template-columns:repeat(auto-fit,minmax(78px,1fr))}
.enh-status-codes .enh-status-item{padding:9px 5px}
.enh-status-codes .enh-status-item b{font-size:18px}
.enh-status-codes .enh-status-item span{font-size:10px}
.enh-note{font-size:10.5px;color:#9ca3af;line-height:1.5;margin-top:9px}
.enh-note b{color:#4b5563}
.enh-empty{font-size:12px;color:#16a34a;background:#f0fdf4;padding:10px 12px;border-radius:8px}
.enh-fail-item{font-size:11px;color:#b91c1c;word-break:break-all;padding:4px 0}
.enh-env{display:grid;grid-template-columns:88px minmax(0,1fr);gap:7px 10px;margin:0;font-size:12px}
.enh-env dt{color:#9ca3af}.enh-env dd{margin:0;color:#374151;word-break:break-all}
.enh-toolbar{display:flex;align-items:center;gap:10px;margin-top:16px}
.enh-toolbar button,.enh-toolbar a{font-size:12px;padding:7px 13px;border-radius:7px;border:1px solid #d8dbe5;
  background:#fff;color:#374151;cursor:pointer;text-decoration:none;font-family:inherit}
.enh-toolbar button:hover,.enh-toolbar a:hover{border-color:#6366f1;color:#4338ca}
.enh-toolbar a{margin-left:auto;background:#eef2ff;border-color:#c7d2fe;color:#4338ca}
.enh-method{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.04em;padding:2px 6px;border-radius:4px;
  background:#eef2ff;color:#4338ca;min-width:40px;text-align:center}
.enh-m-post{background:#ecfdf5;color:#047857}.enh-m-put{background:#fff7ed;color:#c2410c}
.enh-m-patch{background:#f5f3ff;color:#6d28d9}.enh-m-delete{background:#fef2f2;color:#b91c1c}
.enh-path{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:#1f2937;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.enh-spacer{flex:1}
.enh-status,.enh-code,.enh-ms{font-size:10px;padding:2px 6px;border-radius:4px;white-space:nowrap}
.enh-s-ok{background:#ecfdf5;color:#047857}.enh-s-warn{background:#fffbeb;color:#b45309}
.enh-s-err{background:#fef2f2;color:#b91c1c}
.enh-c-ok{background:#f1f5f9;color:#475569}.enh-c-bad{background:#fef2f2;color:#b91c1c}
.enh-ms{color:#9ca3af;font-variant-numeric:tabular-nums}
.enh-ms.enh-slow{background:#fef3c7;color:#b45309;font-weight:600}
details.enh-call{border:1px solid #e8eaf1;border-radius:8px;margin:6px 0;background:#fff;overflow:hidden}
details.enh-call>summary{display:flex;align-items:center;gap:8px;padding:7px 10px;cursor:pointer;list-style:none;background:#fbfcfe}
details.enh-call>summary::-webkit-details-marker{display:none}
details.enh-call>summary:hover{background:#f3f5ff}
.enh-call-body{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:10px;border-top:1px solid #eef0f5}
.enh-call-col{min-width:0}
.enh-call-title{font-size:10px;font-weight:700;color:#6b7280;margin-bottom:5px;letter-spacing:.05em}
.enh-call-title span{color:#c0c5d0;font-weight:400;margin-left:5px}
.enh-call-col pre{margin:0;background:#f8fafc;border:1px solid #eef0f5;border-radius:6px;padding:9px 10px;
  font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10.5px;line-height:1.55;color:#334155;
  max-height:280px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.enh-j-key{color:#7c3aed}.enh-j-num{color:#059669}.enh-j-bool{color:#d97706}
@media(max-width:900px){.enh-grid{grid-template-columns:1fr}.enh-call-body{grid-template-columns:1fr}
  .enh-bar-row{grid-template-columns:100px minmax(0,1fr) 70px}}
</style>
"""

JS = """
<script>
function enhToggleAll(open) {
  document.querySelectorAll('details.enh-call').forEach(function (d) { d.open = open; });
}
</script>
"""
