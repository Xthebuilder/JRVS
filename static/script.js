/* ═══════════════════════════════════════════════════════════
   TENSORLINK — MARKETING SITE JAVASCRIPT
═══════════════════════════════════════════════════════════ */

// ── UTILITY ─────────────────────────────────────────────────
const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

// ── NAV: scroll state + mobile toggle ───────────────────────
const navbar = $('#navbar');
const mobileToggle = $('#mobileToggle');
const navLinks = $('#navLinks');

window.addEventListener('scroll', () => {
  navbar.classList.toggle('scrolled', window.scrollY > 20);
}, { passive: true });

mobileToggle.addEventListener('click', () => {
  navLinks.classList.toggle('open');
  const spans = $$('span', mobileToggle);
  if (navLinks.classList.contains('open')) {
    spans[0].style.transform = 'translateY(7px) rotate(45deg)';
    spans[1].style.opacity = '0';
    spans[2].style.transform = 'translateY(-7px) rotate(-45deg)';
  } else {
    spans.forEach(s => { s.style.transform = ''; s.style.opacity = ''; });
  }
});

// Close nav when a link is clicked
$$('a', navLinks).forEach(a => {
  a.addEventListener('click', () => {
    navLinks.classList.remove('open');
    $$('span', mobileToggle).forEach(s => { s.style.transform = ''; s.style.opacity = ''; });
  });
});

// ── COUNTER ANIMATION ────────────────────────────────────────
function animateCounter(el) {
  const target = parseInt(el.dataset.target, 10);
  const start = parseInt(el.textContent, 10);
  const duration = 1600;
  const step = (timestamp, startTime) => {
    const progress = Math.min((timestamp - startTime) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(start + (target - start) * eased);
    if (progress < 1) requestAnimationFrame(ts => step(ts, startTime));
  };
  requestAnimationFrame(ts => step(ts, ts));
}

// ── INTERSECTION OBSERVER (reveal + counters) ─────────────────
const revealObs = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      entry.target.classList.add('visible');
      revealObs.unobserve(entry.target);
    }
  });
}, { threshold: 0.12 });

const counterObs = new IntersectionObserver(entries => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      animateCounter(entry.target);
      counterObs.unobserve(entry.target);
    }
  });
}, { threshold: 0.5 });

document.addEventListener('DOMContentLoaded', () => {
  // Add reveal class to animatable sections
  const revealTargets = [
    '#how-it-works .step-card',
    '#features .feature-card',
    '#pricing .pricing-card',
    '#testimonials .testimonial-card',
    '#faq .faq-item',
    '#blog .blog-card',
    '.metric-item',
    '#demo .demo-container',
    '.stack-bar-wrapper',
  ];
  revealTargets.forEach(sel => {
    $$(sel).forEach((el, i) => {
      el.classList.add('reveal');
      if (i < 4) el.classList.add(`reveal-delay-${i + 1}`);
      revealObs.observe(el);
    });
  });

  // Counters
  $$('[data-target]').forEach(el => counterObs.observe(el));

  // Init demo
  initDemo();
  initLatencyFlicker();
});

// ── FAQ ACCORDION ─────────────────────────────────────────────
function toggleFaq(id) {
  const item = document.getElementById(id);
  const answer = $('.faq-answer', item);
  const isOpen = item.classList.contains('open');

  // Close all
  $$('.faq-item.open').forEach(openItem => {
    openItem.classList.remove('open');
    $('.faq-answer', openItem).classList.remove('open');
  });

  // Open clicked if it wasn't open
  if (!isOpen) {
    item.classList.add('open');
    answer.classList.add('open');
  }
}

// ── DEMO WIDGET ───────────────────────────────────────────────
const DEMO_CONVERSATIONS = [
  {
    user: 'Summarize the Q2 sales report and flag any anomalies.',
    ai: 'Reading Q2_Sales_Report.pdf... Found 3 anomalies: \n• June 12–14 revenue dip (−34%) — likely holiday weekend\n• Widget Pro category outperformed forecast by +41%\n• 2 accounts flagged for 90+ day overdue status.\nShall I draft a summary email for the leadership team?'
  },
  {
    user: 'Schedule a follow-up with Pacific Logistics for next Tuesday at 2pm.',
    ai: 'Done. I\'ve added "Follow-up: Pacific Logistics" to your calendar for Tuesday, July 29 at 2:00 PM PDT. Calendar invite sent to contact@pacificlogistics.com. Shall I add an agenda or any prep notes?'
  },
  {
    user: 'What are the latest HIPAA requirements for AI tools in healthcare?',
    ai: 'Searching internal knowledge base + web... Key 2024–2025 HIPAA requirements for AI:\n• AI tools processing PHI must have signed BAAs\n• On-premise deployment removes most cloud compliance risk\n• TensorLink\'s local deployment already satisfies these requirements — your data never leaves your network.'
  },
  {
    user: 'Draft a LinkedIn post about our new AI deployment service.',
    ai: '📝 Draft:\n\n"Big news: [Company] just deployed a private AI assistant — powered by LLaMA 3.2 — running entirely on our own hardware. Zero cloud costs. Zero data risk. 100% private.\n\nThanks to TensorLink for making it seamless. If your business is still sending sensitive data to cloud AI, let\'s talk. 🔒"\n\nShall I adjust the tone or length?'
  }
];

let demoIdx = 0;
let demoRunning = false;

function initDemo() {
  const chat = $('#demoChat');
  if (!chat) return;

  runDemoConversation();
}

async function runDemoConversation() {
  if (demoRunning) return;
  demoRunning = true;

  const chat = $('#demoChat');
  const conv = DEMO_CONVERSATIONS[demoIdx % DEMO_CONVERSATIONS.length];
  demoIdx++;

  // Clear if too many messages
  if (chat.children.length > 10) {
    chat.innerHTML = '';
  }

  // Delay before user message
  await sleep(1200);

  // Type user message
  await typeUserMessage(conv.user);
  await sleep(600);

  // Show AI typing indicator
  const typingEl = showTyping();
  await sleep(1500 + Math.random() * 800);
  typingEl.remove();

  // Show AI response
  await showAIMessage(conv.ai);
  await sleep(3500);

  demoRunning = false;
  runDemoConversation();
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function typeUserMessage(text) {
  const chat = $('#demoChat');
  const typingEl = $('#demoTyping');

  // Animate the input field
  if (typingEl) {
    let displayed = '';
    for (const char of text.slice(0, 60)) {
      displayed += char;
      typingEl.textContent = displayed;
      await sleep(28 + Math.random() * 30);
    }
    if (text.length > 60) typingEl.textContent = text.slice(0, 57) + '...';
    await sleep(300);
    typingEl.textContent = 'Ask your private AI anything...';
  }

  appendMessage('user', text, chat);
  scrollChat(chat);
}

async function showAIMessage(text) {
  const chat = $('#demoChat');
  const msgEl = appendMessage('ai', '', chat);
  const bubble = $('.demo-msg-bubble', msgEl);

  // Stream characters
  const lines = text.split('\n');
  for (const line of lines) {
    for (const char of line) {
      bubble.textContent += char;
      await sleep(12 + Math.random() * 18);
    }
    bubble.textContent += '\n';
    scrollChat(chat);
  }
}

function appendMessage(role, text, chat) {
  const div = document.createElement('div');
  div.className = `demo-msg demo-msg--${role}`;
  div.innerHTML = `
    <div class="demo-msg-avatar">${role === 'user' ? 'YOU' : 'AI'}</div>
    <div class="demo-msg-bubble">${text}</div>
  `;
  chat.appendChild(div);
  scrollChat(chat);
  return div;
}

function showTyping() {
  const chat = $('#demoChat');
  const div = document.createElement('div');
  div.className = 'demo-msg demo-msg--ai';
  div.innerHTML = `
    <div class="demo-msg-avatar">AI</div>
    <div class="demo-msg-bubble">
      <div class="demo-msg-typing">
        <span></span><span></span><span></span>
      </div>
    </div>
  `;
  chat.appendChild(div);
  scrollChat(chat);
  return div;
}

function scrollChat(chat) {
  chat.scrollTop = chat.scrollHeight;
}

// Latency flicker
function initLatencyFlicker() {
  const el = $('#demoLatency');
  if (!el) return;

  setInterval(() => {
    const val = 38 + Math.floor(Math.random() * 28);
    el.textContent = `${val}ms`;
  }, 2400);
}

// ── FORM SUBMIT ───────────────────────────────────────────────
function handleFormSubmit(e) {
  e.preventDefault();
  const btn = $('#formSubmitBtn');
  const btnText = $('#formBtnText');

  // Disable
  btn.disabled = true;
  btnText.textContent = 'Sending...';

  // Simulate submission (replace with real endpoint)
  setTimeout(() => {
    const form = $('#contactForm');
    const success = $('#formSuccess');
    form.style.display = 'none';
    success.style.display = 'block';
  }, 1200);
}

// ── SMOOTH SCROLL for anchor links ───────────────────────────
document.addEventListener('click', e => {
  const link = e.target.closest('a[href^="#"]');
  if (!link) return;
  const target = document.querySelector(link.getAttribute('href'));
  if (!target) return;
  e.preventDefault();
  const offset = 70;
  const top = target.getBoundingClientRect().top + window.scrollY - offset;
  window.scrollTo({ top, behavior: 'smooth' });
});
