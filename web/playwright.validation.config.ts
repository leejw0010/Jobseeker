import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'./tests/validation',testMatch:'media-browser.spec.ts',workers:1,fullyParallel:false,timeout:90000,outputDir:'/tmp/jobseeker-media-browser-results',
 use:{baseURL:'http://127.0.0.1:5183',launchOptions:{executablePath:process.env.CHROMIUM_EXECUTABLE_PATH||undefined,args:['--no-sandbox','--autoplay-policy=no-user-gesture-required']}},
 webServer:{command:'npm run dev -- --host 127.0.0.1 --port 5183 --strictPort --mode validation',url:'http://127.0.0.1:5183',reuseExistingServer:false,env:{VITE_E2E_FAKE_FACE:'false',VITE_FACE_MODEL_URL:'http://127.0.0.1:5183/fixture/face.task',VITE_VALIDATION_CODE_VERSION:process.env.VITE_VALIDATION_CODE_VERSION||'unversioned-working-tree',VITE_VALIDATION_DIRTY:'true'}}});
