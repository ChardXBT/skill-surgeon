import pathlib

STYLE = """
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;700&display=swap');
  *{margin:0;padding:0;box-sizing:border-box}
  body{width:1920px;height:1080px;background:#0d1117;color:#e6edf3;font-family:'Inter',sans-serif;
       display:flex;flex-direction:column;justify-content:center;align-items:center;overflow:hidden}
  .mono{font-family:'JetBrains Mono',monospace}
  .kicker{color:#10B981;letter-spacing:.35em;text-transform:uppercase;font-size:26px;font-weight:600}
  h1{font-size:110px;font-weight:800;margin-top:24px;text-align:center;line-height:1.15}
  .sub{font-size:44px;color:#8b949e;margin-top:36px;text-align:center;font-weight:400}
  .row{display:flex;gap:48px;margin-top:80px}
  .chip{background:#161b22;border:1px solid #30363d;border-radius:24px;padding:44px 56px;
        font-size:40px;font-weight:600}
  .chip .bad{color:#f85149}
  .term{background:#161b22;border:1px solid #30363d;border-radius:20px;padding:36px 48px;
        font-size:34px;text-align:left;width:1300px}
  .term .p{color:#10B981}.term .w{color:#d29922}.term .e{color:#f85149}
  .diff{background:#161b22;border:1px solid #30363d;border-radius:20px;padding:36px 48px;
        font-size:32px;width:1300px;text-align:left}
  .del{color:#f85149;background:rgba(248,81,73,.12);display:block;padding:4px 10px}
  .add{color:#3fb950;background:rgba(63,185,80,.12);display:block;padding:4px 10px}
  .btn{display:inline-block;background:#238636;color:#fff;border-radius:12px;
       padding:18px 44px;font-size:32px;font-weight:600;margin-top:48px}
  .url{color:#58a6ff;font-size:40px;margin-top:56px}
"""

WINPATH = "C:\\Users\\ericy\\skills"

frames = {
    "f1": f"<style>{STYLE}</style><div class='kicker'>agent skills</div><h1>Your agent skills<br>rot quietly.</h1>",
    "f2": f"<style>{STYLE}</style><div class='kicker'>the silent failures</div><div class='row'><div class='chip'><span class='bad'>&#10005;</span> dead references</div><div class='chip'><span class='bad'>&#10005;</span> duplicate names</div><div class='chip'><span class='bad'>&#10005;</span> hidden secrets</div></div>",
    "f3": f"<style>{STYLE}</style><div class='kicker'>skill-surgeon</div><div class='term mono'><span class='p'>$</span> surgeon scan ~/.agents/skills<br><br><span class='e'>ERROR</span>  dead bundled reference scripts/report.py<br><span class='w'>WARN</span>   machine-locked path {WINPATH}<br><span class='e'>ERROR</span>  duplicate name across roots<br><span class='p'>AI</span>     trigger collision: pdf-summarizer vs pdf-writer</div><div class='sub'>12 deterministic checks + <b style='color:#10B981'>local AI</b> &mdash; never the cloud</div>",
    "f4": f"<style>{STYLE}</style><div class='kicker'>every repair is an exact diff</div><div class='diff mono'><span class='del'>- python3 .claude/skills/ui-ux-pro-max/scripts/search.py</span><span class='add'>+ python3 scripts/search.py&nbsp;&nbsp;&nbsp;<span style='color:#8b949e'># runs from the skill root</span></span></div><div class='btn'>&#10003;&nbsp;&nbsp;Approve F-001</div><div class='sub' style='margin-top:28px'>Nothing changes without your approval.</div>",
    "f5": f"<style>{STYLE}</style><div class='kicker'>apply &#183; verify &#183; log</div><h1>skill-surgeon</h1><div class='sub'>audits and repairs your agent skills &mdash; free, open source, local-first</div><div class='url mono'>github.com/ChardXBT/skill-surgeon</div>",
}

for name, body in frames.items():
    pathlib.Path(f"{name}.html").write_text(
        f"<html><body>{body}</body></html>", encoding="utf-8")
print("5 frames written")
