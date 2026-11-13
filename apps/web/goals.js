/* QUANTNEX Personal Goals — manual real-funds contributions only. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const api = async (path, options={}) => {
    const response = await fetch("http://127.0.0.1:8000"+path, {
      ...options, headers: {"Content-Type":"application/json", ...(options.headers||{})}, cache:"no-store"
    });
    const type=response.headers.get("content-type")||"";
    if(!response.ok){
      const data=type.includes("application/json")?await response.json().catch(()=>null):null;
      throw new Error(data?.detail||("Request failed ("+response.status+")."));
    }
    return type.includes("application/pdf")?response.blob():response.json();
  };
  const money=(value,currency)=>new Intl.NumberFormat(undefined,{style:"currency",currency,maximumFractionDigits:2}).format(Number(value||0));
  const safeImageUrl=value=>{try{const url=new URL(String(value||"").trim());return url.protocol==="https:"?url.href:"";}catch{return "";}};
  function updateImagePreview(){
    const host=$("goalImagePreview");if(!host)return;
    host.replaceChildren();
    const raw=$("goalImage")?.value.trim()||"";
    if(!raw){const hint=document.createElement("span");hint.textContent="Image preview will appear here.";host.append(hint);return;}
    const url=safeImageUrl(raw);
    if(!url){const hint=document.createElement("span");hint.textContent="Use a direct HTTPS image URL.";host.append(hint);return;}
    const img=document.createElement("img");img.alt="Goal image preview";img.loading="lazy";
    const hint=document.createElement("span");hint.textContent="Loading image preview…";host.append(img,hint);
    img.onload=()=>{hint.textContent="Image preview";};
    img.onerror=()=>{img.remove();hint.textContent="Preview unavailable. Use a direct image-file URL, not a Google Images results page.";};
    img.src=url;
  }
  let goals=[];
  const status=(id,message,bad=false)=>{const node=$(id);if(node){node.textContent=message;node.classList.toggle("goal-error",bad);}};
  function fillSelect(id,items,achievedOnly=false){
    const select=$(id);if(!select)return;
    const previous=select.value;select.replaceChildren();
    const first=document.createElement("option");first.value="";first.textContent=achievedOnly?"Choose an achieved goal":"Choose a goal";select.append(first);
    items.filter(g=>!achievedOnly||g.achieved).forEach(g=>{
      const option=document.createElement("option");option.value=String(g.id);option.textContent=g.title;select.append(option);
    });
    if([...select.options].some(o=>o.value===previous))select.value=previous;
  }
  function render(){
    const host=$("goalCards");if(!host)return;host.replaceChildren();
    if(!goals.length){const empty=document.createElement("article");empty.className="workspace-page-card";empty.textContent="No personal goals yet. Create your first goal above.";host.append(empty);}
    goals.forEach(goal=>{
      const card=document.createElement("article");card.className="goal-card";
      if(goal.image_url){
        const url=safeImageUrl(goal.image_url);
        if(url){
          const link=document.createElement("a");link.className="goal-image-link";link.href=url;link.target="_blank";link.rel="noopener noreferrer";link.setAttribute("aria-label","Open "+goal.title+" image");
          const img=document.createElement("img");img.className="goal-image";img.src=url;img.alt=goal.title;img.loading="lazy";
          img.onerror=()=>{img.remove();const fallback=document.createElement("span");fallback.className="goal-image-fallback";fallback.textContent="Image preview unavailable · open image link";link.append(fallback);};
          link.append(img);card.append(link);
        }
      }
      const top=document.createElement("div");top.className="goal-card-top";
      const title=document.createElement("h3");title.textContent=goal.title;
      const badge=document.createElement("span");badge.className=goal.achieved?"goal-achieved":"goal-active";badge.textContent=goal.achieved?"ACHIEVED":"IN PROGRESS";
      top.append(title,badge);card.append(top);
      const amount=document.createElement("div");amount.className="goal-amounts";
      const saved=document.createElement("strong");saved.textContent=money(goal.saved_amount,goal.currency);
      const target=document.createElement("span");target.textContent="of "+money(goal.target_amount,goal.currency);
      amount.append(saved,target);card.append(amount);
      const progress=document.createElement("div");progress.className="goal-progress";
      const fill=document.createElement("span");fill.style.width=Math.min(100,Number(goal.progress_percent||0))+"%";progress.append(fill);card.append(progress);
      const detail=document.createElement("div");detail.className="goal-detail";
      detail.textContent=goal.achieved?"Completed · "+new Date(goal.achieved_at).toLocaleDateString():"Remaining · "+money(goal.remaining_amount,goal.currency)+" · "+Number(goal.progress_percent||0).toFixed(1)+"%";
      card.append(detail);
      if(goal.target_date&&!goal.achieved){const due=document.createElement("small");due.textContent="Target date · "+new Date(goal.target_date).toLocaleDateString();card.append(due);}
      const bubbles=document.createElement("div");bubbles.className="goal-bubbles";for(let i=0;i<5;i++){const bubble=document.createElement("i");bubble.style.setProperty("--bubble-delay",(i*.7)+"s");bubbles.append(bubble);}card.append(bubbles);
      host.append(card);
    });
    fillSelect("goalContributionSelect",goals);
    fillSelect("goalCertificateSelect",goals,true);
    fillJournalGoalSelect();
  }
  async function load(){
    try{
      const result=await api("/api/v1/goals");goals=result.goals||[];render();
      status("goalsStatus",goals.length+" personal goal(s) · only manually confirmed real savings count.");
    }catch(error){status("goalsStatus",error.message,true);}
  }
  $("goalCreateForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    const title=$("goalTitle").value.trim(),target_amount=Number($("goalTarget").value),image_url=$("goalImage").value.trim();
    if(!title||!Number.isFinite(target_amount)||target_amount<=0){status("goalsStatus","Enter a goal name and a target amount greater than zero.",true);return;}
    if(image_url&&!safeImageUrl(image_url)){status("goalsStatus","Please use a valid direct HTTPS image URL.",true);return;}
    const button=$("goalCreateButton");button.disabled=true;button.textContent="Creating…";
    try{
      await api("/api/v1/goals",{method:"POST",body:JSON.stringify({
        title,target_amount,currency:$("goalCurrency").value,
        initial_amount:0,confirmed_available_real_funds:false,image_url
      })});
      event.target.reset();updateImagePreview();status("goalsStatus","Goal created. Add eligible real savings as you make progress.");await load();
    }catch(error){status("goalsStatus",error.message,true);}
    finally{button.disabled=false;button.textContent="Create personal goal";}
  });
  $("goalAddContribution")?.addEventListener("click",async()=>{
    const id=$("goalContributionSelect").value,amount=Number($("goalContributionAmount").value);
    if(!id||!Number.isFinite(amount)||amount<=0){status("goalContributionStatus","Choose a goal and enter a positive amount.",true);return;}
    if(!$("goalContributionConfirm").checked){status("goalContributionStatus","Confirm these are available real-account funds, not simulated results.",true);return;}
    const button=$("goalAddContribution");button.disabled=true;
    try{
      const result=await api("/api/v1/goals/"+id+"/contributions",{method:"POST",body:JSON.stringify({
        amount,currency:(goals.find(g=>String(g.id)===id)||{}).currency,
        note:"",confirmed_available_real_funds:true
      })});
      $("goalContributionAmount").value="";$("goalContributionConfirm").checked=false;
      status("goalContributionStatus","Saved · "+money(result.saved_amount,(goals.find(g=>String(g.id)===id)||{}).currency)+" · "+result.progress_percent.toFixed(1)+"%"+(result.achieved?" · Goal achieved! Certificate unlocked.":""));
      await load();
    }catch(error){status("goalContributionStatus",error.message,true);}
    finally{button.disabled=false;}
  });

  let certificatePreviewUrl="";
  function showCertificatePreview(blob, filename){
    const frame=$("goalCertificatePreview"),wrap=$("goalCertificatePreviewWrap");
    if(!frame||!wrap)throw new Error("Certificate preview panel is missing. Refresh QUANTNEX after updating.");
    if(certificatePreviewUrl)URL.revokeObjectURL(certificatePreviewUrl);
    certificatePreviewUrl=URL.createObjectURL(blob);
    frame.src=certificatePreviewUrl;
    wrap.hidden=false;
    frame.title=filename;
    wrap.scrollIntoView({behavior:"smooth",block:"nearest"});
  }
  $("goalDemoCertificate")?.addEventListener("click",async()=>{
    const button=$("goalDemoCertificate");button.disabled=true;button.textContent="Preparing preview…";
    try{
      const display_name=$("goalCertificateName")?.value.trim()||"QUANTNEX Demo User";
      const goal_title=$("goalTitle")?.value.trim()||"Sample Personal Goal";
      const blob=await api("/api/v1/goals/demo-certificate",{method:"POST",body:JSON.stringify({display_name,goal_title})});
      showCertificatePreview(blob,"QUANTNEX demo certificate — NOT VALID");
      status("goalCertificateStatus","Demo preview ready for "+display_name+". This sample is permanently marked DEMO ONLY — NOT VALID and cannot be used as a real achievement certificate.");
    }catch(error){status("goalCertificateStatus","Demo certificate preview failed: "+error.message,true);}
    finally{button.disabled=false;button.textContent="Preview demo certificate · NOT VALID";}
  });

  $("goalGenerateCertificate")?.addEventListener("click",async()=>{
    const id=$("goalCertificateSelect").value,display_name=$("goalCertificateName").value.trim();
    if(!id||!display_name){status("goalCertificateStatus","Choose an achieved goal and enter the display name for the certificate.",true);return;}
    const button=$("goalGenerateCertificate");button.disabled=true;button.textContent="Generating…";
    try{
      const blob=await api("/api/v1/goals/"+id+"/certificate",{method:"POST",body:JSON.stringify({display_name})});
      showCertificatePreview(blob,"QUANTNEX achievement certificate");
      const url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="QUANTNEX-Achievement.pdf";document.body.append(link);link.click();link.remove();window.setTimeout(()=>URL.revokeObjectURL(url),30000);
      status("goalCertificateStatus","A4 gold achievement certificate generated and previewed. Verification is local-workspace integrity only.");
    }catch(error){status("goalCertificateStatus",error.message,true);}
    finally{button.disabled=false;button.textContent="Generate A4 certificate";}
  });
  function fillJournalGoalSelect(){
    const select=$("goalJournalImportSelect");if(!select)return;
    const previous=select.value;select.replaceChildren();
    const first=document.createElement("option");first.value="";first.textContent="Choose a goal";select.append(first);
    goals.filter(g=>!g.achieved).forEach(g=>{const option=document.createElement("option");option.value=String(g.id);option.textContent=g.title+" · "+g.currency;select.append(option);});
    if([...select.options].some(x=>x.value===previous))select.value=previous;
  }
  async function previewJournal(){
    const id=$("goalJournalImportSelect").value,host=$("goalJournalCandidates");
    host.replaceChildren();$("goalJournalImport").disabled=true;$("goalJournalConfirm").checked=false;
    if(!id){status("goalJournalStatus","Choose a goal first.",true);return;}
    try{
      const data=await api("/api/v1/goals/"+id+"/journal-preview");
      if(data.goal_currency!=="USD"){status("goalJournalStatus","Journal records have no stored currency. Import is currently limited to USD goals; no FX conversion is inferred.",true);return;}
      if(!data.candidates.length){status("goalJournalStatus","No positive journal records are available for preview.");return;}
      data.candidates.forEach(item=>{
        const label=document.createElement("label");label.className="goal-journal-option";
        const check=document.createElement("input");check.type="checkbox";check.value=String(item.trade_id);check.disabled=!item.eligible;
        const text=document.createElement("span");text.textContent="#"+item.trade_id+" · "+item.symbol+" "+item.direction+" · "+money(item.recorded_pnl,data.goal_currency)+" · "+new Date(item.created_at).toLocaleDateString()+(item.eligible?"":" · already imported");
        label.append(check,text);host.append(label);
      });
      $("goalJournalImport").disabled=false;
      status("Preview only · "+data.candidates.filter(x=>x.eligible).length+" eligible record(s). "+data.warning);
    }catch(error){status("Journal preview failed: "+error.message,true);}
  }
  async function importJournal(){
    const id=$("goalJournalImportSelect").value;
    const trade_ids=[...$("goalJournalCandidates").querySelectorAll('input[type="checkbox"]:checked')].map(x=>Number(x.value));
    if(!id||!trade_ids.length){status("Select at least one eligible journal record.",true);return;}
    if(!$("goalJournalConfirm").checked){status("Confirm that these profits are genuinely received and available real funds.",true);return;}
    const button=$("goalJournalImport");button.disabled=true;
    try{
      const result=await api("/api/v1/goals/"+id+"/journal-import",{method:"POST",body:JSON.stringify({trade_ids,confirmed_available_real_funds:true})});
      status("Imported "+result.imported+" record(s) · "+money(result.amount,result.currency)+" · saved "+money(result.saved_amount,result.currency)+(result.achieved?" · goal achieved":""));
      $("goalJournalCandidates").replaceChildren();$("goalJournalConfirm").checked=false;await load();
    }catch(error){status("Journal import failed: "+error.message,true);}
    finally{button.disabled=false;}
  }
  $("goalJournalPreview")?.addEventListener("click",previewJournal);
  $("goalJournalImport")?.addEventListener("click",importJournal);
  $("goalImage")?.addEventListener("input",updateImagePreview);
  $("goalsRefresh")?.addEventListener("click",load);
  updateImagePreview();
  load();
})();
