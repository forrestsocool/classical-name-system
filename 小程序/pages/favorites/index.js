const {call}=require('../../utils/api');
Page({
  data:{cards:[],comparison:[],selectedCount:0,nextCursor:null,busy:false,error:''},
  onShow(){this.reload();},
  async reload(){if(this.data.busy)return;this.setData({cards:[],comparison:[],selectedCount:0,nextCursor:null});await this.fetchPage();},
  async fetchPage(){if(this.data.busy)return;this.setData({busy:true,error:''});try{await getApp().session();const data=await call('favorites.list',this.data.nextCursor?{before_id:this.data.nextCursor}:{});this.setData({cards:[...this.data.cards,...data.cards],nextCursor:data.next_cursor});}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}},
  more(){this.fetchPage();},
  select(e){const id=Number(e.currentTarget.dataset.id);const current=this.data.cards.find(x=>x.id===id);if(!current)return;if(!current.selected&&this.data.selectedCount>=4){wx.showToast({title:'最多比较四个名字',icon:'none'});return;}const cards=this.data.cards.map(x=>x.id===id?{...x,selected:!x.selected}:x);this.setData({cards,selectedCount:cards.filter(x=>x.selected).length});},
  detail(e){const card=this.data.cards.find(x=>x.id===Number(e.currentTarget.dataset.id));if(!card)return;getApp().selectedCard=card;wx.navigateTo({url:'/pages/detail/index'});},
  async remove(e){if(this.data.busy)return;this.setData({busy:true,error:''});const id=Number(e.currentTarget.dataset.id);try{await call('favorites.remove',{material_id:id});const cards=this.data.cards.filter(x=>x.id!==id);this.setData({cards,selectedCount:cards.filter(x=>x.selected).length,comparison:[]});}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}},
  async compare(){if(this.data.busy)return;this.setData({busy:true,error:''});try{const data=await call('favorites.compare',{material_ids:this.data.cards.filter(x=>x.selected).map(x=>x.id)});this.setData({comparison:data.cards});wx.pageScrollTo({selector:'.comparison',duration:300});}catch(e){this.setData({error:e.message});}finally{this.setData({busy:false});}}
});
