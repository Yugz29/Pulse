import fs from 'node:fs';


export async function readFileContent(filePath: string): Promise<string> {

    try {
        const data = await fs.promises.readFile(filePath, 'utf-8');
        return data;
    } catch (error) {
        console.error(`Erreur lors de la lecture du fichier ${filePath} :`, error);
        return '';
    }
}
