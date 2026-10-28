import {readFileSync} from 'node:fs';
import {defineConfig} from 'vite';
const release=JSON.parse(readFileSync(new URL('../release.json',import.meta.url),'utf8'));
export default defineConfig({define:{__PLUSFOLIO_RELEASE__:JSON.stringify(release)},server:{proxy:{'/api':'http://127.0.0.1:8000'}},build:{outDir:'dist'}});
