Component({
  properties:{show:{type:Boolean,value:false}, mode:{type:String,value:'filter'}, regions:{type:Array,value:[]}, categories:{type:Array,value:[]}, value:{type:Object,value:{}}},
  data:{draft:{region:'CN',include_national:false,category:'全部',doc_type:'全部类型',days:0}, types:[{label:'全部',value:'全部类型'},{label:'政策正文',value:'规范性文件'},{label:'官方解读',value:'政策解读'}], dates:[{label:'不限',value:0},{label:'近7天',value:7},{label:'近30天',value:30},{label:'近90天',value:90}]},
  observers:{'show':function(show) {if(show)this.setData({draft:{region:'CN',include_national:false,category:'全部',doc_type:'全部类型',days:0,...this.properties.value}});}},
  methods:{
    noop(){}, close(){this.triggerEvent('close');},
    choose(e){const {key,value}=e.currentTarget.dataset;this.setData({draft:{...this.data.draft,[key]:key==='days'?Number(value):value}});},
    national(e){this.setData({draft:{...this.data.draft,include_national:!!e.detail.value}});},
    reset(){this.setData({draft:{...this.data.draft,category:'全部',doc_type:'全部类型',days:0}});},
    apply(){this.triggerEvent('apply',this.data.draft);}
  }
});
