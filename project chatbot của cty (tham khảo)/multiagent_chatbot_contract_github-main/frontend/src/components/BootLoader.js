'use client';

import React, { useEffect, useState } from 'react';

export default function BootLoader() {
  const [visible, setVisible] = useState(true);
  const [fadeOut, setFadeOut] = useState(false);

  useEffect(() => {
    const t1 = window.setTimeout(() => setFadeOut(true), 900);
    const t2 = window.setTimeout(() => setVisible(false), 1320);
    return () => {
      window.clearTimeout(t1);
      window.clearTimeout(t2);
    };
  }, []);

  if (!visible) return null;

  return (
    <div className={`bootLoader ${fadeOut ? 'leave' : ''}`}>
      <div className="bootAura" />
      <div className="bootCore">
        <img src="/snowflake.png" alt="NTC" width="76" height="76" className="bootLogo" />
        <p>NTC AI Workspace</p>
        <div className="bootBar">
          <div className="bootBarInner" />
        </div>
      </div>
    </div>
  );
}
