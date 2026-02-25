import { simpleGit } from 'simple-git';
import { config } from '../config.js';


export async function getChurnScore(filePath: string): Promise<number> {
    try {
        const git = simpleGit(config.projectPath);
        const log = await git.log({ file: filePath, '--since': '30 days ago' });
        return log.total;
    } catch {
        return 0;
    }
}
