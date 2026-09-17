const {call,requestId,storageKey}=require('../../utils/api');
Page({
  data:{editing:true,surname:'',required:'',excluded:'',nameLength:2,lengthIndex:1,lengthLabels:['单字名','双字名'],busy:false,saving:false,current:null,remaining:0,error:'',hint:'暂时没有符合条件的新名字，可以稍后再看或放宽条件。',cooldown:0},
  async onLoad(){
    this.cards=[];this.pending=null;
    try{this.user=await getApp().session();const saved=wx.getStorageSync(storageKey(this.user));
      if(saved && saved.conditions){const c=saved.conditions;this.setData({surname:c.surname,nameLength:c.name_length,lengthIndex:c.name_length-1,required:c.required||'',excluded:c.excluded||'',editing:false});this.cards=Array.isArray(saved.cards)?saved.cards:[];this.pending=saved.pending||null;this.showCard();}
    }catch(e){this.setData({error:e.message});}
  },
  onUnload(){clearInterval(this.timer);},
  input(e){this.setData({[e.currentTarget.dataset.field]:e.detail.value.trim()});},
  lengthChange(e){this.setData({lengthIndex:Number(e.detail.value),nameLength:Number(e.detail.value)+1});},
  conditions(){return {surname:this.data.surname,name_length:this.data.nameLength,required:this.data.required,excluded:this.data.excluded,count:8};},
  persist(){if(this.user)wx.setStorageSync(storageKey(this.user),{conditions:this.activeConditions||this.conditions(),cards:this.cards,pending:this.pending});},
  showCard(){this.setData({current:this.cards[0]||null,remaining:this.cards.length});},
  edit(){if(!this.data.busy){this.editingFrom=this.activeConditions||this.conditions();this.setData({editing:true,error:''});}},
  async start(){
    if(this.data.busy)return;
    const c=this.conditions();if(!/^[\u3400-\u9fff]{1,2}$/.test(c.surname)||!/^[\u3400-\u9fff]{0,2}$/.test(c.required)||!/^[\u3400-\u9fff]{0,32}$/.test(c.excluded)){this.setData({error:'请填写汉字姓氏、固定字和避用字'});return;}
    if(c.required.length>c.name_length||[...c.required].some(ch=>c.excluded.includes(ch))){this.setData({error:'固定字与字数或避用字冲突'});return;}
    const old=this.activeConditions||this.editingFrom;
    if(!old||JSON.stringify(old)!==JSON.stringify(c)){this.cards=[];this.pending=null;clearInterval(this.timer);this.setData({cooldown:0});}
    this.activeConditions=c;this.setData({editing:false,error:''});this.showCard();this.persist();if(!this.cards.length)await this.load();
  },
  async load(){
    if(this.data.busy||this.data.cooldown>0)return;this.setData({busy:true,error:''});
    try{this.user=await getApp().session();this.activeConditions=this.conditions();
      if(!this.pending)this.pending={...this.activeConditions,request_id:requestId()};this.persist();
      const result=await call('feed.pull',this.pending);this.cards=result.cards;this.pending=null;this.persist();this.showCard();
      if(!this.cards.length){this.setData({hint:result.message,cooldown:result.retry_after||15});clearInterval(this.timer);this.timer=setInterval(()=>{const n=Math.max(0,this.data.cooldown-1);this.setData({cooldown:n});if(!n)clearInterval(this.timer);},1000);}
    }catch(e){if(e.status===422||e.status===409){this.pending=null;this.persist();}this.setData({error:e.message});}finally{this.setData({busy:false});}
  },
  skip(){if(this.data.busy||!this.cards.length)return;this.cards.shift();this.persist();this.showCard();if(!this.cards.length)this.load();},
  async favorite(){if(this.data.busy||!this.data.current)return;this.setData({busy:true,saving:true,error:''});try{await call('favorites.add',{material_id:this.data.current.id});this.cards.shift();this.persist();this.showCard();wx.showToast({title:'已收藏',icon:'success'});}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false,saving:false});}if(!this.cards.length)this.load();},
  detail(){if(!this.data.current)return;getApp().selectedCard=this.data.current;wx.navigateTo({url:'/pages/detail/index'});},
  touchStart(e){this.touch=e.touches.length===1?{x:e.touches[0].clientX,y:e.touches[0].clientY}:null;},
  touchCancel(){this.touch=null;},
  touchEnd(e){if(!this.touch||!e.changedTouches.length)return;const t=e.changedTouches[0],dx=t.clientX-this.touch.x,dy=t.clientY-this.touch.y;this.touch=null;if(Math.abs(dx)>70&&Math.abs(dx)>Math.abs(dy)*1.5){if(dx>0)this.favorite();else this.skip();}}
});
