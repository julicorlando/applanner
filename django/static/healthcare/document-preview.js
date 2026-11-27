// Live preview of clinical documents: mirrors the PDF layout (healthcare/document_pdf.py)
// while the text is typed, so the professional sees the result before issuing it.
(function () {
  'use strict';
  var source = document.getElementById('doc-preview-data');
  var paper = document.querySelector('[data-paper]');
  if (!source || !paper) return;
  var data = JSON.parse(source.textContent);
  var LABEL = /^([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ /().º°-]{1,38}):(\s.*|)$/;
  var JUSTIFIED = { certificate: true, declaration: true };
  var SAMPLE = {
    nome_paciente: (data.patient && data.patient.name) || 'Nome do paciente',
    cpf_paciente: (data.patient && data.patient.cpf) || '000.000.000-00',
    nome_profissional: data.professional.name || 'Nome do profissional',
    clinica: data.clinic.name,
    data: data.date
  };

  function field(name) { return document.querySelector('[data-preview-' + name + ']'); }
  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function kind() {
    var input = field('kind');
    return (input && input.value) || data.kind || 'declaration';
  }
  function patient() {
    var select = field('patient');
    var info = Object.assign({}, data.patient || {});
    if (select && select.value && (!info.name || String(select.dataset.initial) !== String(select.value))) {
      var option = select.options[select.selectedIndex];
      info = { name: option ? option.text : '' };
    }
    return info;
  }
  function substitute(text) {
    if (!field('variables')) return text;
    return text.replace(/\{(nome_paciente|cpf_paciente|nome_profissional|clinica|data)\}/g, function (_, key) { return SAMPLE[key]; });
  }
  function line(text, justify) {
    if (text.indexOf('## ') === 0) return el('p', 'doc-subtitle', text.slice(3).trim());
    var match = LABEL.exec(text);
    if (match && !justify) {
      var p = el('p', 'doc-line');
      p.appendChild(el('b', '', match[1] + ':'));
      p.appendChild(document.createTextNode(match[2]));
      return p;
    }
    var node = el('p', justify ? 'doc-line doc-justify' : 'doc-line', text);
    if (!text.trim()) node.innerHTML = '&nbsp;';
    return node;
  }

  function render() {
    var current = kind();
    var title = field('title');
    var body = field('body');
    var text = substitute(body ? body.value : '');
    var who = patient();
    var justify = !!JUSTIFIED[current];
    paper.style.setProperty('--doc-color', data.clinic.color);

    var head = paper.querySelector('[data-paper-head]');
    head.textContent = '';
    if (data.clinic.logo) {
      var logo = el('img', 'doc-logo');
      logo.src = data.clinic.logo; logo.alt = data.clinic.name;
      head.appendChild(logo);
      var mark = paper.querySelector('[data-paper-watermark]');
      if (mark && !mark.src) mark.src = data.clinic.logo;
    } else {
      head.appendChild(el('strong', 'doc-brand', data.clinic.name));
    }

    var content = paper.querySelector('[data-paper-body]');
    content.textContent = '';
    content.appendChild(el('h3', 'doc-title', data.titles[current] || (title && title.value || '').toUpperCase()));
    if (current === 'prescription') {
      var para = el('p', 'doc-line');
      para.appendChild(el('b', '', 'Para:'));
      para.appendChild(document.createTextNode(' ' + (who.name || 'Nome do paciente')));
      content.appendChild(para);
      content.appendChild(el('div', 'doc-gap'));
    } else if (current === 'budget') {
      [['Paciente', 'name'], ['CPF', 'cpf'], ['Endereço', 'address'], ['Data de Nascimento', 'birth_date'], ['Fone', 'phone']].forEach(function (pair) {
        var value = who[pair[1]] || (pair[1] === 'name' ? 'Nome do paciente' : '');
        if (!value) return;
        var row = el('p', 'doc-line');
        row.appendChild(el('b', '', pair[0] + ':'));
        row.appendChild(document.createTextNode(' ' + value));
        content.appendChild(row);
      });
      content.appendChild(el('div', 'doc-gap'));
    } else if (who.name && text.toLowerCase().indexOf(who.name.toLowerCase()) === -1) {
      content.appendChild(el('p', 'doc-line', 'Paciente: ' + who.name + (who.cpf ? ' · CPF: ' + who.cpf : '')));
      content.appendChild(el('div', 'doc-gap'));
    }
    if (text.trim()) {
      text.split(/\r?\n/).forEach(function (raw) { content.appendChild(line(raw.replace(/\s+$/, ''), justify)); });
    } else {
      content.appendChild(el('p', 'doc-placeholder', field('template') && field('template').value
        ? 'O texto do modelo escolhido entra aqui ao preparar o documento.'
        : 'Comece a digitar o texto ao lado para ver o documento aqui.'));
    }

    var sign = paper.querySelector('[data-paper-sign]');
    sign.textContent = '';
    sign.appendChild(el('p', 'doc-date', data.date));
    if (data.signature_url) {
      var img = el('img', 'doc-signature');
      img.src = data.signature_url; img.alt = 'Assinatura cadastrada';
      img.addEventListener('error', function () { img.replaceWith(el('div', 'doc-signature-empty', 'Assinatura cadastrada aparece aqui')); });
      sign.appendChild(img);
    } else {
      sign.appendChild(el('div', 'doc-signature-empty', 'Assinatura do profissional'));
    }
    sign.appendChild(el('div', 'doc-rule'));
    sign.appendChild(el('strong', 'doc-signer', data.professional.name || 'Nome do profissional'));
    sign.appendChild(el('span', '', data.professional.role));
    if (data.professional.registration) sign.appendChild(el('span', '', data.professional.registration));
  }

  function fit() {
    var frame = paper.parentElement;
    var scale = Math.min(1, frame.clientWidth / 595);
    paper.style.transform = 'scale(' + scale + ')';
    frame.style.height = Math.ceil(paper.offsetHeight * scale) + 'px';
  }

  ['title', 'body', 'kind', 'patient', 'template'].forEach(function (name) {
    var input = field(name);
    if (!input) return;
    input.addEventListener('input', function () { render(); fit(); });
    input.addEventListener('change', function () { render(); fit(); });
  });
  document.querySelectorAll('[data-kind-choice]').forEach(function (button) {
    button.addEventListener('click', function () {
      var input = field('kind');
      if (!input) return;
      input.value = button.getAttribute('data-kind-choice');
      document.querySelectorAll('[data-kind-choice]').forEach(function (other) {
        other.setAttribute('aria-pressed', other === button ? 'true' : 'false');
      });
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });
  });
  render();
  fit();
  if (window.ResizeObserver) new ResizeObserver(fit).observe(paper.parentElement);
  else window.addEventListener('resize', fit);
})();
