/* No PHI or encryption keys in localStorage, CacheStorage or plaintext IndexedDB. */
(function(root) {
  'use strict';
  const enc = new TextEncoder(), dec = new TextDecoder();
  const base64 = bytes => btoa(String.fromCharCode(...bytes));
  const bytes = value => Uint8Array.from(atob(value), c => c.charCodeAt(0));
  async function derive(password, salt) {
    if (typeof password !== 'string' || password.length < 12) throw Error('Use uma senha local com pelo menos 12 caracteres.');
    const material = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveKey']);
    return crypto.subtle.deriveKey({name:'PBKDF2', salt, iterations:310000, hash:'SHA-256'}, material,
      {name:'AES-GCM', length:256}, false, ['encrypt', 'decrypt']);
  }
  async function seal(value, key, salt) {
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const encrypted = new Uint8Array(await crypto.subtle.encrypt({name:'AES-GCM', iv, additionalData:enc.encode('applanner-clinic-v1')}, key, enc.encode(JSON.stringify(value))));
    // Chunked conversion avoids stack overflow on large snapshots.
    let binary = ''; for (let i=0; i<encrypted.length; i+=8192) binary += String.fromCharCode(...encrypted.subarray(i,i+8192));
    return {schema:1, salt:base64(salt), iv:base64(iv), ciphertext:btoa(binary)};
  }
  async function open(envelope, password) {
    if (envelope?.schema !== 1) throw Error('Cofre local inválido.');
    const salt = bytes(envelope.salt), key = await derive(password, salt);
    let raw;
    try { raw = await crypto.subtle.decrypt({name:'AES-GCM', iv:bytes(envelope.iv), additionalData:enc.encode('applanner-clinic-v1')}, key, bytes(envelope.ciphertext)); }
    catch { throw Error('Senha incorreta ou cofre local danificado.'); }
    const value = JSON.parse(dec.decode(raw));
    if (!value.snapshot?.scope || !Array.isArray(value.queue)) throw Error('Conteúdo do cofre inválido.');
    return {value, key, salt};
  }
  function storage() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open('applanner-clinic-v1', 1);
      request.onupgradeneeded = () => request.result.createObjectStore('sealed');
      request.onerror = () => reject(Error('Armazenamento local indisponível.'));
      request.onsuccess = () => resolve(request.result);
    });
  }
  async function io(mode, action) {
    const db = await storage();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction('sealed', mode), request = action(tx.objectStore('sealed'));
        tx.oncomplete = () => resolve(request.result);
        tx.onabort = tx.onerror = () => reject(Error('Não foi possível salvar no dispositivo. O registro não foi confirmado.'));
      });
    } finally { db.close(); }
  }
  root.ClinicVault = {derive, seal, open,
    load:() => io('readonly', store => store.get('current')),
    save:value => io('readwrite', store => store.put(value, 'current')),
    erase:() => io('readwrite', store => store.delete('current'))};
})(globalThis);
