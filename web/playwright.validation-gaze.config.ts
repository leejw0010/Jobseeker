import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests/validation',testMatch:'gaze-attempts.spec.ts',workers:1,timeout:45000,outputDir:'/tmp/jobseeker-validation-gaze-results',
 use:{baseURL:'http://127.0.0.1:5185',viewport:{width:1000,height:700},launchOptions:{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH||undefined,args:['--no-sandbox','--use-fake-device-for-media-stream','--use-fake-ui-for-media-stream']}},
 webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5185 --strictPort --mode validation',url:'http://127.0.0.1:5185',reuseExistingServer:false,env:{VITE_E2E_FAKE_FACE:'true',VITE_GAZE_LAB:'true'}}});
