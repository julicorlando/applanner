(()=>{'use strict';document.querySelectorAll('[data-structured-clinical]').forEach(form=>{
const kind=form.dataset.structuredClinical,editor=form.querySelector('[data-structured-editor]'),field=form.querySelector('[name=payload]');
let data;try{data=JSON.parse(field.value||'null')}catch(_){};
const table=document.createElement('table');editor.append(table);
function input(type,value,change,attrs={}){const node=document.createElement('input');node.type=type;if(type==='checkbox')node.checked=Boolean(value);else node.value=value??'';Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,v));node.addEventListener('input',()=>{change(type==='checkbox'?node.checked:type==='number'?(node.value===''?null:Number(node.value)):node.value);sync()});return node}
function cell(row,value){const td=document.createElement('td');if(typeof value==='string')td.textContent=value;else td.append(value);row.append(td)}
function sync(){field.value=JSON.stringify(data);const total=form.querySelector('[data-plan-total]');if(total)total.textContent=data.reduce((n,line)=>n+(Number(line.price)||0)*(Number(line.quantity)||0),0).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function head(labels){const tr=document.createElement('tr');labels.forEach(label=>{const th=document.createElement('th');th.textContent=label;tr.append(th)});table.append(tr)}
if(kind==='periodontal'){
if(!data||Array.isArray(data))data={};head(['Dente FDI','Mobilidade (0–3)','Sítio','Sondagem mm','Recessão mm','Sangramento']);
[1,2,3,4,5,6,7,8].forEach(q=>{for(let n=1;n<=(q<5?8:5);n++){const id=''+q+n;const rowData=data[id]||{mobility:0,sites:{}};
['MV','V','DV','ML','L','DL'].forEach((site,index)=>{const tr=document.createElement('tr');const values=rowData.sites[site]||{probing:null,recession:null,bleeding:false};
const update=()=>{if(values.probing!==null&&values.recession!==null)rowData.sites[site]=values;else delete rowData.sites[site];data[id]=rowData};cell(tr,id);cell(tr,index===0?input('number',rowData.mobility,v=>{rowData.mobility=v;update()},{min:0,max:3,'aria-label':'Mobilidade '+id}):'');cell(tr,site);
cell(tr,input('number',values.probing,v=>{values.probing=v;update()},{min:0,max:20,step:.5,'aria-label':'Sondagem '+id+' '+site}));cell(tr,input('number',values.recession,v=>{values.recession=v;update()},{min:-10,max:20,step:.5,'aria-label':'Recessão '+id+' '+site}));cell(tr,input('checkbox',values.bleeding,v=>{values.bleeding=v;update()},{'aria-label':'Sangramento '+id+' '+site}));table.append(tr)})}});
}else{
if(!Array.isArray(data))data=[];
function draw(){table.replaceChildren();head(['Dente FDI / geral','Procedimento','Quantidade','Valor unitário (R$)','']);data.forEach((line,index)=>{const tr=document.createElement('tr');cell(tr,input('text',line.tooth,v=>line.tooth=v,{maxlength:2,'aria-label':'Dente do item '+(index+1)}));cell(tr,input('text',line.procedure,v=>line.procedure=v,{maxlength:200,required:true,'aria-label':'Procedimento '+(index+1)}));cell(tr,input('number',line.quantity,v=>line.quantity=v,{min:1,max:99,'aria-label':'Quantidade '+(index+1)}));cell(tr,input('number',line.price,v=>line.price=String(v),{min:0,max:999999.99,step:.01,'aria-label':'Preço '+(index+1)}));const remove=document.createElement('button');remove.type='button';remove.textContent='Remover';remove.onclick=()=>{data.splice(index,1);draw();sync()};cell(tr,remove);table.append(tr)})}
form.querySelector('[data-add-line]').onclick=()=>{if(data.length>=100)return;data.push({tooth:'',procedure:'',quantity:1,price:'0.00'});draw();sync()};if(!data.length)data.push({tooth:'',procedure:'',quantity:1,price:'0.00'});draw();
}sync();form.addEventListener('submit',sync);
})})();
