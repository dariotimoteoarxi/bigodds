// Todas as rotas /api/* do Bigodds na Cloudflare Pages (a lógica está em cloud/worker-core.js).
import { handle } from '../../cloud/worker-core.js';

export const onRequest = ({ request, env }) => handle(request, env);
