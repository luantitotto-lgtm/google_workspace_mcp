(()=>{
  const $=x=>document.getElementById(x), escapeHTML=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let responses=[];
  const showLogin=()=>{$('loginStage').hidden=false;$('dashboard').hidden=true;};
  function draw(){
    const confirmed=responses.filter(r=>r.attendance==='yes');
    const stats=[['RESPOSTAS',responses.length],['CONFIRMADOS',confirmed.length],['RECUSAS',responses.length-confirmed.length],['TOTAL DE PESSOAS',confirmed.reduce((s,r)=>s+1+(r.guest_names||[]).length,0)]];
    $('stats').innerHTML=stats.map(([n,v])=>`<div class="stat"><strong>${v}</strong><small>${n}</small></div>`).join('');
    const q=$('search').value.trim().toLowerCase(),f=$('filter').value;
    let filtered=responses.filter(r=>(f==='all'||f===r.attendance) && `${r.full_name} ${r.email} ${r.phone}`.toLowerCase().includes(q));
    $('rows').innerHTML=filtered.map(r=>`<tr><td>${escapeHTML(r.full_name)}</td><td>${escapeHTML(r.email)}<br/>${escapeHTML(r.phone)}</td><td>${r.attendance==='yes'?'Sim':'Não'}</td><td>${escapeHTML((r.guest_names||[]).join(', ')||'—')}</td><td>${escapeHTML(r.dietary||'—')}</td><td>${escapeHTML(r.note||'—')}</td><td>${new Date(r.updated_at*1000).toLocaleString('pt-BR')}</td></tr>`).join('') || '<tr><td colspan="7">Nenhuma resposta encontrada.</td></tr>';
  }
  async function load(){
    const r=await fetch('/api/admin/responses',{cache:'no-store'});
    if(!r.ok) {showLogin();return;}
    responses=await r.json();$('loginStage').hidden=true;$('dashboard').hidden=false;draw();
  }
  $('loginForm').addEventListener('submit',async e=>{
    e.preventDefault();$('loginError').textContent='';
    try{const r=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:$('adminPassword').value})});const data=await r.json();if(!r.ok)throw Error(data.detail||'Não foi possível entrar.');$('adminPassword').value='';await load();}
    catch(e){$('loginError').textContent=e.message;}
  });
  $('search').addEventListener('input',draw);$('filter').addEventListener('change',draw);
  $('csvButton').addEventListener('click',()=>location.href='/api/admin/export');
  $('logout').addEventListener('click',async()=>{await fetch('/api/admin/logout',{method:'POST'});showLogin();});
  load().catch(()=>showLogin());
})();