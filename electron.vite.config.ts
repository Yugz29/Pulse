import { defineConfig } from 'electron-vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'node:path';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
    main: {
        build: {
            rollupOptions: {
                input: 'src/main/index.ts',
                external: [
                    'better-sqlite3',
                    'electron',
                    'tree-sitter',
                    'tree-sitter-typescript',
                    'tree-sitter-javascript',
                    'tree-sitter-python',
                ],
            }
        }
    },
    preload: {
        build: {
            rollupOptions: {
                input: 'src/preload/index.ts',
                output: {
                    format: 'cjs',
                    entryFileNames: 'index.js',
                }
            }
        }
    },
    renderer: {
        root: resolve(__dirname, 'src/renderer'),
        plugins: [react(), tailwindcss()]
    }
});
