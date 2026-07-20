'use client';

import { useEffect } from 'react';

export default function InteractionFX() {
  useEffect(() => {
    const selector = 'button, a, [role="button"], .ripple-surface';

    const onPointerDown = (event) => {
      const host = event.target.closest(selector);
      if (!host) return;

      const rect = host.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height) * 1.25;
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;

      host.classList.add('ripple-host');

      const ripple = document.createElement('span');
      ripple.className = 'water-ripple';
      ripple.style.width = `${size}px`;
      ripple.style.height = `${size}px`;
      ripple.style.left = `${x - size / 2}px`;
      ripple.style.top = `${y - size / 2}px`;

      host.appendChild(ripple);
      ripple.addEventListener('animationend', () => ripple.remove(), { once: true });
    };

    document.addEventListener('pointerdown', onPointerDown, { passive: true });
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
    };
  }, []);

  return null;
}
