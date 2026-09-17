const {call}=require('../../utils/api');
Page({
  data:{card:null,elements:[],unknown:'',popularity:'未命中已收录的历史热门资料，不代表实时重名率。',busy:false,error:''},
  onLoad(){const card=getApp().selectedCard;if(!card)return;const w=card.item.五行匹配||{};const hot=card.item.热门提示||{};const hints=Array.isArray(hot.提示)?hot.提示.join('；'):hot.提示;this.setData({card,elements:Object.entries(w.已知字符||{}).map(([char,element])=>({char,element})),unknown:(w.未知字符||[]).join('、'),popularity:hints ? hints+'。'+(hot.说明||'') : this.data.popularity});},
  async favorite(){if(this.data.busy)return;this.setData({busy:true,error:''});try{await call('favorites.add',{material_id:this.data.card.id});wx.showToast({title:'已收藏',icon:'success'});}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}},
  feedback(){if(this.data.busy)return;const kinds=['出处问题','释义问题'];wx.showActionSheet({itemList:kinds,success:async result=>{this.setData({busy:true,error:''});try{await call('feedback.save',{material_id:this.data.card.id,kind:kinds[result.tapIndex]});wx.showToast({title:'感谢反馈',icon:'success'});}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}}});}
});
