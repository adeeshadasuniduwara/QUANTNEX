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
    const host=$("goalCards");host.replaceChildren();
    if(!goals.length){const empty=document.createElement("article");empty.className="workspace-page-card";empty.textContent="No personal goals yet. Create your first goal above.";host.append(empty);}
    goals.forEach(goal=>{
      const card=document.createElement("article");card.className="goal-card";
      if(goal.image_url){
        const img=document.createElement("img");img.className="goal-image";img.src=goal.image_url;img.alt=goal.title;img.loading="lazy";
        img.onerror=()=>img.remove();card.append(img);
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
  }
  async function load(){
    try{
      const result=await api("/api/v1/goals");goals=result.goals||[];render();
      status("goalsStatus",goals.length+" personal goal(s) · only manually confirmed real savings count.");
    }catch(error){status("goalsStatus",error.message,true);}
  }
  $("goalCreateForm")?.addEventListener("submit",async event=>{
    event.preventDefault();
    const title=$("goalTitle").value.trim(),target_amount=Number($("goalTarget").value),initial_amount=Number($("goalInitial").value||0);
    if(initial_amount>0&&!$("goalInitialConfirm").checked){status("goalsStatus","Confirm that starting savings are genuinely available real money.",true);return;}
    const button=$("goalCreateButton");button.disabled=true;button.textContent="Creating…";
    try{
      await api("/api/v1/goals",{method:"POST",body:JSON.stringify({
        title,description:$("goalDescription").value.trim(),target_amount,currency:$("goalCurrency").value,
        initial_amount,confirmed_available_real_funds:$("goalInitialConfirm").checked,
        target_date:$("goalTargetDate").value?$("goalTargetDate").value+"T12:00:00":null,
        image_url:$("goalImage").value.trim()
      })});
      event.target.reset();$("goalInitial").value="0";status("goalsStatus","Goal created. Add eligible real savings as you make progress.");await load();
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
        note:$("goalContributionNote").value.trim(),confirmed_available_real_funds:true
      })});
      $("goalContributionAmount").value="";$("goalContributionNote").value="";$("goalContributionConfirm").checked=false;
      status("goalContributionStatus","Saved · "+money(result.saved_amount,(goals.find(g=>String(g.id)===id)||{}).currency)+" · "+result.progress_percent.toFixed(1)+"%"+(result.achieved?" · Goal achieved! Certificate unlocked.":""));
      await load();
    }catch(error){status("goalContributionStatus",error.message,true);}
    finally{button.disabled=false;}
  });
  $("goalGenerateCertificate")?.addEventListener("click",async()=>{
    const id=$("goalCertificateSelect").value,display_name=$("goalCertificateName").value.trim();
    if(!id||!display_name){status("goalCertificateStatus","Choose an achieved goal and enter the display name for the certificate.",true);return;}
    const button=$("goalGenerateCertificate");button.disabled=true;button.textContent="Generating…";
    try{
      const blob=await api("/api/v1/goals/"+id+"/certificate",{method:"POST",body:JSON.stringify({display_name})});
      const url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download="QUANTNEX-Achievement.pdf";document.body.append(link);link.click();link.remove();URL.revokeObjectURL(url);
      status("goalCertificateStatus","A4 achievement certificate generated. Verification is local-workspace integrity only.");
    }catch(error){status("goalCertificateStatus",error.message,true);}
    finally{button.disabled=false;button.textContent="Generate A4 certificate";}
  });
  $("goalsRefresh")?.addEventListener("click",load);
  load();
})();
