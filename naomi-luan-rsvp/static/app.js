(() => {
  const $ = id => document.getElementById(id);
  const intro = $('intro');
  const tokenFromUrl = new URLSearchParams(location.search).get('edit');
  const editToken = { value: tokenFromUrl || '' };
  const skipIntro = sessionStorage.getItem('nl_invite_opened') === 'true' || !!tokenFromUrl || matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (skipIntro) intro.classList.add('hide');
  $('openInvite').addEventListener('click', () => {
    sessionStorage.setItem('nl_invite_opened', 'true');
    intro.classList.add('opening');
    setTimeout(() => { intro.classList.add('hide'); $('inicio').scrollIntoView({behavior:'smooth'}); }, 1230);
  });
  const form = $('rsvpForm');
  const yesFields = $('yesFields');
  const guestNames = $('guestNames');
  const companionSelect = $('companions');
  const btn = $('submitButton');
  const error = $('formError');
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const selectedAttendance = () => document.querySelector('input[name="attendance"]:checked')?.value;
  const showError = m => { error.textContent = m; error.hidden = false; error.scrollIntoView({behavior:'smooth',block:'center'}); };
  const clearError = () => { error.hidden = true; error.textContent = ''; };
  function toggleYes() { yesFields.hidden = selectedAttendance() !== 'yes'; guestNames.querySelectorAll('input').forEach(input => { input.disabled = yesFields.hidden; }); }
  function renderGuests(names = []) {
    let count = Number(companionSelect.value);
    guestNames.innerHTML = '';
    for (let i=0;i<count;i++) {
      let wrap = document.createElement('label'); wrap.className = 'field';
      wrap.innerHTML = `Nome do acompanhante ${i+1} <span>*</span><input class="guest-name" type="text" maxlength="100" required placeholder="Nome completo"/>`;
      wrap.querySelector('input').value = names[i] || ''; wrap.querySelector('input').disabled = yesFields.hidden;
      guestNames.appendChild(wrap);
    }
  }
  form.querySelectorAll('input[name="attendance"]').forEach(e=>e.addEventListener('change',toggleYes));
  companionSelect.addEventListener('change',()=>renderGuests());
  function dataFromForm() {
    return {
      full_name: $('fullName').value.trim(), email:$('email').value.trim(), phone:$('phone').value.trim(),
      attendance:selectedAttendance(), guest_names:selectedAttendance()==='yes' ? [...document.querySelectorAll('.guest-name')].map(x=>x.value.trim()) : [],
      dietary:selectedAttendance()==='yes' ? $('dietary').value.trim() : '', note:$('note').value.trim(),
      privacy_consent:$('privacy').checked, website:$('website').value
    };
  }
  function renderReceipt(receipt, token) {
    $('formStage').hidden = true;
    const link = `${location.origin}/?edit=${encodeURIComponent(token)}#rsvp`;
    const yes = receipt.attendance === 'yes';
    $('receiptStage').innerHTML = `<div class="receipt"><div class="receipt-icon">✦</div><h3>${yes?'Esperamos por você!':'Com carinho, sempre'}</h3><p>${yes ? 'Sua presença foi confirmada com sucesso.' : 'Recebemos sua resposta e agradecemos por nos avisar.'}</p><p><strong>${escapeHTML(receipt.full_name)}</strong>${yes&&receipt.guest_names?.length?`<br/>Acompanhantes: ${escapeHTML(receipt.guest_names.join(', '))}`:''}</p><div class="protocol">PROTOCOLO ${escapeHTML(receipt.protocol)}</div><p style="font-size:17px;margin:28px 0 12px">Guarde o link privado abaixo caso precise alterar sua resposta.</p><div class="editlink">${escapeHTML(link)}</div><button type="button" id="copyLink">COPIAR LINK PRIVADO</button><button type="button" id="editAgain">ALTERAR RESPOSTA</button><p style="font-size:15px;color:#716b57;margin-top:24px">21 de novembro de 2026 · Isola del Garda, Itália</p></div>`;
    $('receiptStage').hidden = false;
    $('copyLink').addEventListener('click', async e => {try { await navigator.clipboard.writeText(link);e.target.textContent='LINK COPIADO'; } catch { e.target.textContent='SELECIONE E COPIE O LINK ACIMA'; }});
    $('editAgain').addEventListener('click',()=>{ $('receiptStage').hidden=true;$('formStage').hidden=false;$('formStage').scrollIntoView({behavior:'smooth'}); });
    history.replaceState({},'',`/?edit=${encodeURIComponent(token)}#rsvp`);
    $('rsvp').scrollIntoView({behavior:'smooth'});
  }
  function populate(data) {
    $('fullName').value = data.full_name || '';
    $('email').value = data.email || '';
    $('phone').value = data.phone || '';
    form.querySelector(`input[name="attendance"][value="${data.attendance}"]`).checked = true;
    toggleYes();
    companionSelect.value = String(data.guest_names?.length || 0);
    renderGuests(data.guest_names || []);
    $('dietary').value = data.dietary || '';
    $('note').value = data.note || '';
    $('privacy').checked = true;
    btn.innerHTML='ATUALIZAR RESPOSTA <span>↗</span>';
  }
  if (tokenFromUrl) {
    fetch(`/api/rsvp/${encodeURIComponent(tokenFromUrl)}`,{cache:'no-store'})
      .then(async r => { if(!r.ok) throw Error('Este link de edição não é válido ou expirou.'); return r.json(); })
      .then(data => {populate(data); $('rsvp').scrollIntoView(); })
      .catch(e=>showError(e.message));
  }
  fetch('/api/status', {cache:'no-store'}).then(r=>r.json()).then(s=>{
    if (!s.ready) {
      btn.disabled=true;
      btn.textContent='CONFIRMAÇÕES EM PREPARAÇÃO';
      error.textContent='A confirmação de presença será liberada quando o banco de dados estiver conectado. Não envie dados ainda.';
      error.hidden=false;
    }
  }).catch(()=>{ btn.disabled=true;btn.textContent='SERVIÇO INDISPONÍVEL';});
  form.addEventListener('submit', async e=>{
    e.preventDefault(); clearError();
    if (!form.checkValidity()) { form.reportValidity();return; }
    if (!selectedAttendance()) {showError('Selecione se poderá comparecer.');return;}
    const data = dataFromForm();
    if (data.attendance === 'yes' && data.guest_names.some(n=>n.length<2)) {showError('Informe o nome completo de cada acompanhante.');return;}
    btn.disabled = true; btn.textContent='ENVIANDO...';
    try {
      const method = editToken.value?'PUT':'POST';
      const url = editToken.value?`/api/rsvp/${encodeURIComponent(editToken.value)}`:'/api/rsvp';
      const res = await fetch(url,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
      const result=await res.json();
      if (!res.ok) { const detail=result.detail; throw Error(typeof detail==='string'?detail:'Não foi possível enviar seus dados. Confira o formulário e tente novamente.'); }
      editToken.value=result.edit_token;
      renderReceipt(result.receipt,result.edit_token);
    } catch(err){showError(err.message||'Não foi possível enviar. Tente novamente.');}
    finally {btn.disabled=false;btn.innerHTML=editToken.value?'ATUALIZAR RESPOSTA <span>↗</span>':'ENVIAR CONFIRMAÇÃO <span>↗</span>';}
  });
})();