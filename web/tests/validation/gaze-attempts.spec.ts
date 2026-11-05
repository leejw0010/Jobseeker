import {test,expect,type Page} from '@playwright/test';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
async function start(page:Page){
 await page.addInitScript(()=>{localStorage.setItem('e2e-face-detector','gaze');localStorage.setItem('e2e-gaze-scale','0.1');});
 await page.goto('/dev/gaze-lab');await page.getByRole('button',{name:'동의하고 카메라 켜기'}).click();await expect(page.getByText('얼굴이 화면 안에 있어요')).toBeVisible();await page.getByLabel('주기 시험 건너뛰기').check();await page.getByRole('button',{name:'시험 시작',exact:true}).click();await expect(page.getByTestId('lab-prompt')).toBeVisible();
}
async function exported(page:Page){const downloaded=page.waitForEvent('download');await page.getByRole('button',{name:'익명 Gaze 집계 내보내기(JSON)'}).click();const file=await downloaded;return JSON.parse(readFileSync((await file.path())!,'utf8'));}
test('invalid and aborted attempts are exportable with separate status, safe reasons and environment',async({page})=>{
 await start(page);await page.setViewportSize({width:900,height:700});await expect(page.getByText('창 크기·위치·배율이 바뀌어 이번 시험은 무효예요')).toBeVisible();
 let rows=await exported(page);expect(rows).toHaveLength(1);expect(rows[0].status).toBe('invalid');expect(rows[0].reasonCodes).toEqual(['viewport_changed']);expect(rows[0].environment.delegate).toBe('synthetic');expect(rows[0].environment.cameraWidth).toBeGreaterThan(0);expect(rows[0].environment.cameraHeight).toBeGreaterThan(0);
 await page.getByRole('button',{name:'시험 시작',exact:true}).click();await expect(page.getByTestId('lab-prompt')).toBeVisible();await page.getByRole('button',{name:'시험 중단',exact:true}).click();
 rows=await exported(page);expect(rows).toHaveLength(2);expect(rows[1].status).toBe('aborted');expect(rows[1].reasonCodes).toEqual(['user_aborted']);expect(rows[1].evidence).toBe('synthetic-signal');
 const out=process.env.VALIDATION_RESULTS_DIR||'/tmp/jobseeker-media-browser-artifacts';mkdirSync(out,{recursive:true});writeFileSync(join(out,'gaze-attempts.json'),JSON.stringify(rows,null,2));
 expect(JSON.stringify(rows)).not.toMatch(/landmark|transcript|answerId|token|rawFrame/);await page.getByRole('button',{name:'모든 시도 지우기'}).click();await expect(page.getByRole('button',{name:'익명 Gaze 집계 내보내기(JSON)'})).toHaveCount(0);
});
