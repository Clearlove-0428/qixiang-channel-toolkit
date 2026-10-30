const {spawnSync}=require('node:child_process');
const path=require('node:path');
const tests=process.argv.includes('--unit')?['test_catalog.cjs','test_time_utils.cjs']:
 ['test_catalog.cjs','test_time_utils.cjs','test_browser_extractor.cjs','test_auto_collect.cjs','test_background_capture.cjs','test_workspace_ui.cjs'];
for(const name of tests){
 const result=spawnSync(process.execPath,[path.join(__dirname,'../频道文本工具/tests',name)],{stdio:'inherit',env:process.env});
 if(result.error){console.error(result.error.message);process.exit(1);}
 if(result.status!==0)process.exit(result.status||1);
}
