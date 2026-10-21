const fs = require('node:fs');
const path = require('node:path');
const {instance} = require('@viz-js/viz');
const {chromium} = require('playwright');

const output = __dirname;
const theme = `
graph [bgcolor="white", pad="0.45", nodesep="0.42", ranksep="0.58", splines=polyline, compound=true, fontname="Microsoft JhengHei", fontsize=25, fontcolor="#24324B", labelloc=t];
node [shape=box, style="rounded,filled", fillcolor="#F3F0FF", color="#A99BD0", penwidth=1.5, fontname="Microsoft JhengHei", fontsize=21, fontcolor="#24324B", margin="0.22,0.17"];
edge [color="#738399", penwidth=1.65, arrowsize=0.8, fontname="Microsoft JhengHei", fontsize=15, fontcolor="#506078"];
`;

const overview = `digraph overall {
${theme}
rankdir=TB;
label="整體系統架構\nAI Butler · 考試智伴｜MAIN eb46068";
U [label="使用者\n學生、老師、同學", fillcolor="#EAF2FF", color="#8AAAD2"];
UI [label="網頁介面\nHTML／CSS／JavaScript／Jinja2", fillcolor="#EAF2FF", color="#8AAAD2"];
APP [label="Flask 後端\n路由、登入驗證、權限與 CSRF 保護", fillcolor="#E8EDFF", color="#8594CB", penwidth=2];
U -> UI;
UI -> APP [dir=both, label="請求與回應"];
subgraph cluster_modules {
  label="功能模組｜同一套 Flask 應用，非獨立微服務";
  color="#C6BDDE"; bgcolor="#FBFAFE"; style="rounded"; penwidth=1.4; margin=20;
  {rank=same;
    BASE [label="共用平台\n帳號註冊、驗證信\n個人資料"];
    STUDY [label="考試與學習\n教材／題庫、模考、錯題\nRAG 問答、學習規劃"];
    LIFE [label="生活與升學\n運動訓練、收支記帳\n學測落點"];
  }
}
APP -> STUDY [lhead=cluster_modules];
DB [label="遠端 MariaDB\n帳號、教材片段、題庫\n成績、生活紀錄", shape=cylinder, fillcolor="#EAF7F1", color="#8CB8A2"];
BASE -> DB; STUDY -> DB; LIFE -> DB;
BACKUP [label="本機 SQLite 備援\n主庫失聯時唯讀", shape=cylinder, fillcolor="#F3F6F9", color="#ABB6C2"];
DB -> BACKUP [style=dashed, label="定期建立快照"];
SMTP [label="SMTP 郵件服務\n寄送註冊驗證碼", fillcolor="#FFF5E7", color="#D3B387"];
BASE -> SMTP;
FILES [label="本機檔案儲存\n上傳原檔、閱讀副本\n模型權重", fillcolor="#EAF7F1", color="#8CB8A2"];
STUDY -> FILES;
JOB [label="背景 AI 工作\n執行緒池、進度\n取消、接續"];
STUDY -> JOB;
LEDGER [label="本機 ai_jobs.sqlite\n工作紀錄、checkpoint\n用量與快取", shape=cylinder, fillcolor="#EAF7F1", color="#8CB8A2"];
JOB -> LEDGER;
CPU [label="本機 CPU 模型\nE5 語意排序、OCR\n選配 NLI 輔助判斷", fillcolor="#FFF5E7", color="#D3B387"];
STUDY -> CPU;
AI [label="LLM 模型服務\n解析補修、答案推定\n分類、生成與教學", fillcolor="#FFF5E7", color="#D3B387"];
JOB -> AI; LIFE -> AI;
CSV [label="歷年學測 CSV\n檢定與篩選門檻", fillcolor="#EAF7F1", color="#8CB8A2"];
LIFE -> CSV;
{rank=same; SMTP; FILES; JOB; CPU; CSV;}
{rank=same; LEDGER; AI;}
NOTE [label="架構說明：MariaDB 為業務資料與教材文字儲存；運動模組使用獨立模型設定。\nSQLite 工作帳本可寫，備援快照唯讀；目前沒有離線寫入後自動同步。", shape=plain, fillcolor="white", fontsize=17, fontcolor="#596780"];
BACKUP -> NOTE [style=invis]; LEDGER -> NOTE [style=invis]; AI -> NOTE [style=invis];
}`;

const rag = `digraph rag {
${theme}
rankdir=TB;
label="核心：教材 RAG 問答架構\n依使用者、科目與章節限定教材來源";
subgraph cluster_ingest {
  label="教材建立"; color="#BDCFDF"; bgcolor="#FAFCFF"; style="rounded"; margin=20;
  FILE [label="使用者上傳教材\nPDF／Word／文字", fillcolor="#EAF2FF", color="#8AAAD2"];
  PARSE [label="本機解析與必要 OCR\n保留原檔、頁碼與來源資訊"];
  CHUNK [label="切成知識片段\n保留片段與教材的對應關係"];
  DB [label="MariaDB\n教材、片段及來源定位", shape=cylinder, fillcolor="#EAF7F1", color="#8CB8A2"];
  FILE -> PARSE -> CHUNK -> DB;
}
ASK [label="使用者提出問題\n指定科目／章節", fillcolor="#EAF2FF", color="#8AAAD2"];
FILTER [label="範圍檢索\n先限制使用者、科目與章節"];
DB -> FILTER [label="範圍內教材"];
ASK -> FILTER [label="問題與選取範圍"];
RANK [label="詞彙檢索＋CPU E5 語意重排\n選出相關教材片段"];
LLM [label="LLM 整理回答\n根據片段說明並附來源編號", fillcolor="#FFF5E7", color="#D3B387"];
CHECK [label="引用檢查與教材支持複核\n依據不足時不顯示無支持答案", fillcolor="#FFF5E7", color="#D3B387"];
ANSWER [label="呈現回答與教材來源\n保存對話紀錄", fillcolor="#EAF7F1", color="#8CB8A2"];
FILTER -> RANK -> LLM -> CHECK -> ANSWER;
NOTE [label="RAG 負責檢索與限縮依據；LLM 負責理解與整理，不是重新訓練模型。\n目前為 MariaDB 文字儲存＋本機混合檢索，非獨立向量資料庫。", shape=plain, fillcolor="white", fontsize=17, fontcolor="#596780"];
ANSWER -> NOTE [style=invis];
}`;

(async () => {
  const viz=await instance();
  const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
  try {
    const metricsPage=await browser.newPage();
    for (const [name, source] of [['整體系統架構',overview],['教材RAG問答架構',rag]]) {
      // Graphviz WASM cannot measure Windows CJK fonts. Measure in Chromium
      // and provide explicit box dimensions, keeping the exact original labels.
      let dot=source;
      const nodes=Array.from(source.matchAll(/\b([A-Z][A-Z_]*)\s*\[([^\]]+)\]/g));
      for(const node of nodes) {
        const label=node[2].match(/label="([^"]*)"/);
        if(!label || /shape=plain/.test(node[2])) continue;
        const lines=label[1].split(/\\n|\n/);
        const size=Number(node[2].match(/fontsize=(\d+)/)?.[1] || 21);
        const width=await metricsPage.evaluate(({lines,size})=>{
          const ctx=document.createElement('canvas').getContext('2d');
          ctx.font=`${size}px "Microsoft JhengHei", sans-serif`;
          return Math.max(...lines.map(line=>ctx.measureText(line).width));
        },{lines,size});
        dot=dot.replace(node[0],node[0].slice(0,-1)+`, fixedsize=true, width=${((width+48)/72).toFixed(3)}, height=${((lines.length*size*1.5+26)/72).toFixed(3)}]`);
      }
      fs.writeFileSync(path.join(output,name+'.dot'),dot,'utf8');
      let svg=viz.renderString(dot,{format:'svg',engine:'dot'});
      const viewBox=svg.match(/viewBox="([^"]+)"/)[1].split(/\s+/).map(Number);
      const [,,width,height]=viewBox;
      // Fixed CSS pixels + a 2x screenshot retain crisp Traditional Chinese.
      svg=svg.replace(/width="[^"]+" height="[^"]+"/,`width="${width}" height="${height}"`);
      fs.writeFileSync(path.join(output,name+'.svg'),svg,'utf8');
      const page=await browser.newPage({viewport:{width:Math.ceil(width),height:Math.ceil(height)},deviceScaleFactor:2});
      await page.setContent(`<html lang="zh-Hant"><head><meta charset="utf-8"><style>html,body{margin:0;background:white}svg{display:block}text{font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif}</style></head><body>${svg}</body></html>`);
      await page.evaluate(()=>document.fonts.ready);
      const overflow=await page.evaluate(()=>Array.from(document.querySelectorAll('g.node')).flatMap(node=>{
        if(node.querySelector('title')?.textContent==='NOTE') return [];
        const shape=node.querySelector('path,polygon,ellipse');
        if(!shape) return [];
        const b=shape.getBoundingClientRect();
        return Array.from(node.querySelectorAll('text')).filter(text=>{
          const t=text.getBoundingClientRect();
          return t.left<b.left-2 || t.right>b.right+2 || t.top<b.top-3 || t.bottom>b.bottom+3;
        }).map(t=>t.textContent);
      }));
      if(overflow.length) throw new Error(name+' text outside node: '+JSON.stringify(overflow));
      await page.screenshot({path:path.join(output,name+'.png'),fullPage:true});
      console.log(JSON.stringify({file:name+'.png',width:Math.ceil(width)*2,height:Math.ceil(height)*2,textOverflow:overflow}));
      await page.close();
    }
    await metricsPage.close();
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1)});
