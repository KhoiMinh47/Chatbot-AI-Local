"""
Controller xử lý các API endpoint liên quan đến hợp đồng (Contract).

Bao gồm các chức năng:
    - Upload template hợp đồng.
    - Tạo hợp đồng từ template.
    - Download hợp đồng đã tạo.
    - Xem lịch sử và quản lý session hợp đồng.
"""

from fastapi import APIRouter, Depends, Form, UploadFile, File, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session
from typing import List

from auth.auth_middleware import require_roles, require_vllm_ready
from database.setup_postgres import get_db
from database.table.table_postgres import Account
from request.contract_request import (
    ContractTemplatedRequest,
    ContractFastRequest,
    ContractReasoningRequest,
    ContractPathRequest,
)
from request.history_request import history_request
from service.contract_service import (
    upload_template_service,
    create_contract_templated_service,
    create_contract_fast_service,
    create_contract_reasoning_service,
    load_template_name,
    delete_template_service,
    download_contract,
    load_contract_list,
    delete_contract_service,
    add_contract_session_path_service,
    delete_contract_session_path_service,
)

router = APIRouter()





@router.post("/upload-multiple-templates")
async def upload_multiple_templates(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["upload"])),
):
    """Upload nhiều file template hợp đồng (.docx) cùng lúc."""

    results = []
    for file in files:
        try:
            res = await upload_template_service(file, db)
            results.append({"filename": file.filename, "status": "ok"})
        except Exception as e:
            results.append({"filename": file.filename, "status": "error", "detail": str(e)})

    return {"status": 200, "results": results}


@router.post("/create-contract-templated")
async def create_contract_templated(
    request: ContractTemplatedRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["create"])),
    _vllm: None = Depends(require_vllm_ready),
):
    """Luồng 1: Tạo hợp đồng với SSE streaming dựa trên Template."""
    return StreamingResponse(
        await create_contract_templated_service(request, db, user_id=str(current_user.id)),
        media_type="text/event-stream"
    )

@router.post("/create-contract-fast")
async def create_contract_fast(
    request: ContractFastRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["create"])),
    _vllm: None = Depends(require_vllm_ready),
):
    """Luồng 2: LLM tạo hợp đồng siêu nhanh không cần template."""
    return StreamingResponse(
        await create_contract_fast_service(request, db, user_id=str(current_user.id)),
        media_type="text/event-stream"
    )

@router.post("/create-contract-reasoning")
async def create_contract_reasoning(
    request: ContractReasoningRequest,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["create"])),
    _vllm: None = Depends(require_vllm_ready),
):
    """Luồng 3: Multi-Agent AI tạo hợp đồng chặt chẽ qua cơ chế kiểm duyệt."""
    return StreamingResponse(
        await create_contract_reasoning_service(request, db, user_id=str(current_user.id)),
        media_type="text/event-stream"
    )

@router.get("/download-contract/{filename:path}")
def download_file(filename: str):
    """Download file hợp đồng đã tạo theo tên file."""

    return download_contract(filename)


@router.get("/load-template")
async def load_template(
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["create"])),
):
    """Lấy danh sách tất cả template hợp đồng đã upload."""

    return await load_template_name(db)


@router.get("/load-contract")
async def load_contract(
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["create"])),
):
    """Lấy danh sách tất cả hợp đồng đã tạo của current user."""

    return await load_contract_list(db, user_id=str(current_user.id))


@router.delete("/delete-template/{id}")
async def delete_template(
    id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["upload"])),
):
    """
    Xóa template hợp đồng theo ID.
    Lưu ý: Khi xóa template, nếu có hợp đồng nào đang sử dụng template này thì sẽ bị xóa cùng.
    """

    return await delete_template_service(db, id)


@router.delete("/delete-contract/{id}")
async def delete_contract(
    id: int,
    db: Session = Depends(get_db),
    current_user: Account = Depends(require_roles(["create"])),
):
    """Xóa hợp đồng theo ID."""

    return await delete_contract_service(db, id)




@router.post("/session/path")
async def pin_contract_session_path(
    request: ContractPathRequest,
    current_user: Account = Depends(require_roles(["create"])),
):
    """Ghi đè template_path cho phiên Hợp đồng."""
    return await add_contract_session_path_service(
        session_id=request.session_id,
        file_path=request.file_path,
        user_id=str(current_user.id)
    )


@router.delete("/session/path")
async def unpin_contract_session_path(
    request: ContractPathRequest,
    current_user: Account = Depends(require_roles(["create"])),
):
    """Xóa ghim (xóa template_path) khỏi phiên Hợp đồng."""
    return await delete_contract_session_path_service(
        session_id=request.session_id,
        file_path=request.file_path,
        user_id=str(current_user.id)
    )


@router.get("/test-upload-multiple-templates", response_class=HTMLResponse)
def test_upload_multiple_templates_page():
    """Trang HTML test upload nhiều file template hợp đồng."""

    return """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <title>Test Upload Multiple Templates</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
            .container { background: #1e293b; border-radius: 16px; padding: 40px; max-width: 600px; width: 90%; box-shadow: 0 25px 50px rgba(0,0,0,0.4); }
            h1 { font-size: 24px; margin-bottom: 8px; background: linear-gradient(135deg, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
            p.sub { color: #94a3b8; margin-bottom: 24px; font-size: 14px; }
            .upload-area { border: 2px dashed #334155; border-radius: 12px; padding: 32px; text-align: center; cursor: pointer; transition: all 0.3s; margin-bottom: 20px; }
            .upload-area:hover { border-color: #38bdf8; background: #1e293b; }
            .upload-area.dragover { border-color: #818cf8; background: rgba(129,140,248,0.1); }
            .upload-area input { display: none; }
            .upload-area .icon { font-size: 40px; margin-bottom: 8px; }
            .file-list { margin-bottom: 20px; }
            .file-item { background: #334155; border-radius: 8px; padding: 10px 14px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; }
            .file-item .name { color: #e2e8f0; } .file-item .size { color: #64748b; }
            .file-item .remove { color: #f87171; cursor: pointer; font-weight: bold; }
            button { width: 100%; padding: 14px; background: linear-gradient(135deg, #38bdf8, #818cf8); color: #fff; border: none; border-radius: 10px; font-size: 16px; font-weight: 600; cursor: pointer; transition: opacity 0.2s; }
            button:hover { opacity: 0.9; } button:disabled { opacity: 0.5; cursor: not-allowed; }
            .result { margin-top: 24px; background: #0f172a; border-radius: 10px; padding: 16px; max-height: 400px; overflow-y: auto; font-size: 13px; white-space: pre-wrap; word-break: break-word; display: none; }
            .result.show { display: block; }
            .loader { display: none; text-align: center; margin-top: 16px; color: #38bdf8; }
            .loader.show { display: block; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📄 Upload Templates Hợp Đồng</h1>
            <p class="sub">Upload nhiều file template cùng lúc</p>

            <div class="upload-area" id="dropZone" onclick="document.getElementById('fileInput').click()">
                <div class="icon">📁</div>
                <div>Click hoặc kéo thả file vào đây</div>
                <input type="file" id="fileInput" multiple>
            </div>

            <div class="file-list" id="fileList"></div>

            <button id="submitBtn" onclick="submitFiles()" disabled>🚀 Upload Templates</button>

            <div class="loader" id="loader">⏳ Đang xử lý... (Vui lòng đợi)</div>
            <pre class="result" id="result"></pre>
        </div>

        <script>
            let selectedFiles = [];
            const fileInput = document.getElementById('fileInput');
            const fileList = document.getElementById('fileList');
            const submitBtn = document.getElementById('submitBtn');
            const dropZone = document.getElementById('dropZone');

            fileInput.addEventListener('change', (e) => addFiles(e.target.files));

            dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('dragover'); });
            dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
            dropZone.addEventListener('drop', (e) => { e.preventDefault(); dropZone.classList.remove('dragover'); addFiles(e.dataTransfer.files); });

            function addFiles(files) {
                for (const f of files) {
                    selectedFiles.push(f);
                }
                renderFileList();
            }

            function removeFile(idx) { selectedFiles.splice(idx, 1); renderFileList(); }

            function renderFileList() {
                fileList.innerHTML = selectedFiles.map((f, i) =>
                    `<div class="file-item"><span class="name">${f.name}</span><span class="size">${(f.size/1024).toFixed(0)} KB</span><span class="remove" onclick="removeFile(${i})">✕</span></div>`
                ).join('');
                submitBtn.disabled = selectedFiles.length === 0;
            }

            async function submitFiles() {
                const fd = new FormData();
                selectedFiles.forEach(f => fd.append('files', f));
                submitBtn.disabled = true;
                document.getElementById('loader').classList.add('show');
                document.getElementById('result').classList.remove('show');
                try {
                    const res = await fetch('/api/v1/contracts/upload-multiple-templates', { method: 'POST', body: fd });
                    const data = await res.json();
                    document.getElementById('result').textContent = JSON.stringify(data, null, 2);
                    document.getElementById('result').classList.add('show');
                    if (res.ok) {
                        selectedFiles = [];
                        renderFileList();
                    }
                } catch (err) {
                    document.getElementById('result').textContent = 'Error: ' + err.message;
                    document.getElementById('result').classList.add('show');
                }
                document.getElementById('loader').classList.remove('show');
                submitBtn.disabled = false;
            }
        </script>
    </body>
    </html>
    """


@router.get("/test-create-contract", response_class=HTMLResponse)
def test_create_contract_page():
    """Trang HTML test API create-contract-templated với SSE real-time."""

    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>Test Contract Stream</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;height:100vh;display:grid;grid-template-rows:auto 1fr;padding:16px;gap:12px}
h1{font-size:18px;background:linear-gradient(135deg,#38bdf8,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.main{display:grid;grid-template-columns:300px 1fr;gap:12px;overflow:hidden}
.panel{background:#1e293b;border-radius:10px;padding:16px;overflow:auto}
label{display:block;font-size:11px;color:#94a3b8;margin:10px 0 3px}
input,textarea{width:100%;background:#0f172a;border:1px solid #334155;border-radius:6px;color:#e2e8f0;padding:7px 9px;font-size:13px;outline:none;font-family:inherit}
textarea{min-height:80px;resize:vertical}
.btn{margin-top:10px;width:100%;padding:9px;border:none;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;color:#fff}
.btn-go{background:linear-gradient(135deg,#38bdf8,#818cf8)}
.btn-clear{background:#334155;margin-top:6px}
.btn:disabled{opacity:.4;cursor:not-allowed}
.right{display:flex;flex-direction:column;gap:8px;overflow:hidden}
.statusbar{display:flex;align-items:center;gap:8px;background:#1e293b;border-radius:8px;padding:8px 12px;font-size:12px;flex-shrink:0}
.dot{width:7px;height:7px;border-radius:50%;background:#475569;flex-shrink:0}
.dot.run{background:#38bdf8;animation:p 1s infinite}
.dot.ok{background:#4ade80}
.dot.err{background:#f87171}
@keyframes p{0%,100%{opacity:1}50%{opacity:.3}}
#out{background:#0f172a;border-radius:8px;padding:14px;flex:1;overflow-y:auto;font-size:12px;line-height:1.8;font-family:Consolas,monospace;white-space:pre-wrap;word-break:break-all}
.c-node{color:#38bdf8;font-weight:bold}
.c-ok{color:#4ade80;font-weight:bold}
.c-err{color:#f87171;font-weight:bold}
</style>
</head>
<body>
<h1>⚡ Test Streaming Contract Creation</h1>
<div class="main">
  <div class="panel">
    <div style="margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid #334155">
      <label style="margin-top:0">Tài khoản (để nhận Token)</label>
      <div style="display:flex;gap:8px;margin-bottom:8px">
         <input id="em" value="ngbao3558@gmail.com" placeholder="Email">
         <input id="pw" type="password" value="35683568" placeholder="Pass">
      </div>
      <button class="btn btn-go" style="margin-top:0" onclick="login()">🔑 Đăng nhập</button>
      <div id="lst" style="font-size:11px;margin-top:8px;color:#f87171">Chưa đăng nhập (Nếu chưa đăng nhập sẽ bị lỗi 401)</div>
    </div>
    
    <label>Luồng tạo hợp đồng</label>
    <select id="mode" onchange="document.getElementById('t_group').style.display = this.value === 'templated' ? 'block' : 'none';" style="width:100%;background:#0f172a;border:1px solid #334155;border-radius:6px;color:#e2e8f0;padding:7px 9px;font-size:13px;outline:none;font-family:inherit;margin-bottom:6px">
      <option value="templated">Luồng 1: Template (Điền mẫu)</option>
      <option value="fast">Luồng 2: Fast (Tạo nhanh không mẫu)</option>
      <option value="reasoning">Luồng 3: Reasoning (Multi-Agent)</option>
    </select>
    <label>Session ID (-1 = tạo mới)</label><input id="s" type="number" value="-1">
    <div id="t_group">
      <label>Template ID</label><input id="t" type="number" value="1">
    </div>
    <label>Yêu cầu</label>
    <textarea id="q">Tạo hợp đồng dịch vụ giữa Công ty ABC và Công ty XYZ, giá trị 500 triệu, thời hạn 12 tháng</textarea>
    <button class="btn btn-go" id="btn" onclick="go()">▶ Bắt đầu</button>
    <button class="btn btn-clear" onclick="clr()">🗑 Xóa</button>
  </div>
  <div class="right">
    <div class="statusbar">
      <div class="dot" id="dot"></div>
      <span id="st">Sẵn sàng</span>
      <span id="tc" style="margin-left:auto;color:#64748b;font-size:11px"></span>
    </div>
    <div id="out">Kết quả hiện ở đây...</div>
  </div>
</div>
<script>
let rd=null,tc=0;
const out=()=>document.getElementById('out');
const st=(s,t)=>{document.getElementById('dot').className='dot '+s;document.getElementById('st').textContent=t};
const app=(txt,cls)=>{
  const o=out();
  if(cls){const sp=document.createElement('span');sp.className=cls;sp.textContent=txt;o.appendChild(sp);}
  else o.appendChild(document.createTextNode(txt));
  o.scrollTop=o.scrollHeight;
};
async function login(){
  const e=document.getElementById('em').value;
  const p=document.getElementById('pw').value;
  document.getElementById('lst').textContent='Đang đăng nhập...';
  document.getElementById('lst').style.color='#94a3b8';
  try{
    const r=await fetch('/api/v1/auth/login',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({email:e,password:p})
    });
    if(r.ok){
      document.getElementById('lst').textContent='✅ Đã đăng nhập (Cookie lưu thành công)';
      document.getElementById('lst').style.color='#4ade80';
    }else{
      document.getElementById('lst').textContent='❌ Lỗi: '+(await r.text());
      document.getElementById('lst').style.color='#f87171';
    }
  }catch(err){
    document.getElementById('lst').textContent='❌ Lỗi mạng: '+err.message;
    document.getElementById('lst').style.color='#f87171';
  }
}
function clr(){out().textContent='';st('','Sẵn sàng');document.getElementById('tc').textContent='';tc=0;}
async function go(){
  if(rd){try{rd.cancel();}catch(e){}rd=null;}
  const mode = document.getElementById('mode').value;
  const body=JSON.stringify({
    session_id:parseInt(document.getElementById('s').value),
    template_id:parseInt(document.getElementById('t').value),
    user_input:document.getElementById('q').value
  });
  out().textContent='';tc=0;
  document.getElementById('btn').disabled=true;
  st('run','Đang kết nối...');
  try{
    const endpoint = '/api/v1/contracts/create-contract-' + mode;
    const res=await fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body});
    if(!res.ok){const e=await res.text();app('HTTP '+res.status+': '+e,'c-err');st('err','Lỗi '+res.status);document.getElementById('btn').disabled=false;return;}
    rd=res.body.getReader();
    const dec=new TextDecoder();
    let buf='';
    while(true){
      const{done,value}=await rd.read();
      if(done)break;
      buf+=dec.decode(value,{stream:true});
      const parts=buf.split('\\n\\n');
      buf=parts.pop();
      for(const p of parts){
        const line=p.trim();
        if(!line.startsWith('data:'))continue;
        try{
          const ev=JSON.parse(line.slice(5).trim());
          if(ev.title&&!ev.mess){
            const isErr = ev.title.includes('Lỗi');
            const cls = ev.end ? (isErr ? 'c-err' : 'c-ok') : 'c-node';
            app('\\n\\n[' + ev.title + ']\\n', cls);
            app(JSON.stringify(ev) + '\\n');
            st(ev.end ? (isErr ? 'err' : 'ok') : 'run', ev.title);
          }
          if(ev.mess){app(ev.mess);tc++;document.getElementById('tc').textContent=tc+' tokens';}
          if(ev.end){
            if(ev.download_url){
                app('\\n\\n✅ Đã tạo xong: ' + ev.path_name, 'c-ok');
                const o = out();
                const a = document.createElement('a');
                a.href = ev.download_url;
                a.textContent = '\\n🔗 Nhấn vào đây để tải file Hợp đồng này';
                a.style.color = '#38bdf8';
                a.style.display = 'block';
                a.style.marginTop = '8px';
                a.style.textDecoration = 'none';
                a.style.fontWeight = 'bold';
                a.target = '_blank';
                o.appendChild(a);
                o.scrollTop = o.scrollHeight;
            }
            document.getElementById('btn').disabled=false;rd=null;
          }
        }catch(e){console.warn('SSE parse err',e);}
      }
      if(!rd) break;
    }
  }catch(e){app('\\nLỗi: '+e.message,'c-err');st('err','Lỗi');document.getElementById('btn').disabled=false;}
}
</script>
</body>
</html>"""