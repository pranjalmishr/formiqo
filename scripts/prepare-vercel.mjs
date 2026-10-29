import {cp,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
// Include a pinned, Lambda-compatible Chromium with the Python function, not a
// runtime download from an arbitrary URL. Source includes its license notice.
const from=fileURLToPath(new URL('../node_modules/@sparticuz/chromium/',import.meta.url));
const to=fileURLToPath(new URL('../backend/app/runtime_assets/chromium/',import.meta.url));
await mkdir(to,{recursive:true});
await cp(from+'bin',to+'bin',{recursive:true});
await cp(from+'LICENSE',to+'LICENSE');
console.log('Pinned Chromium assets staged for the Vercel Python function.');
