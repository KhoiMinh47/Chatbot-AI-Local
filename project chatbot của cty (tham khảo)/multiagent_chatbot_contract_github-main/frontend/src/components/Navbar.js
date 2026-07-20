// "use client";
// import React, { useEffect, useRef, useState } from 'react';
// import Link from 'next/link';
// import styles from '../styles/Navbar.module.css';

// function Navbar() {
//   const [isOpen, setIsOpen] = useState(false);
//   const [theme, setTheme] = useState('light');
//   const dropdownRef = useRef(null);

//   const toggleMenu = () => setIsOpen((v) => !v);

//   // Theme toggle logic
//   useEffect(() => {
//     if (typeof window !== 'undefined') {
//       document.documentElement.setAttribute('data-theme', theme);
//       localStorage.setItem('theme', theme);
//     }
//   }, [theme]);

//   useEffect(() => {
//     // Load theme from localStorage
//     if (typeof window !== 'undefined') {
//       const saved = localStorage.getItem('theme');
//       if (saved) setTheme(saved);
//     }
//     const handleClickOutside = (event) => {
//       if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
//         setIsOpen(false);
//       }
//     };
//     document.addEventListener('mousedown', handleClickOutside);
//     return () => {
//       document.removeEventListener('mousedown', handleClickOutside);
//     };
//   }, []);

//   return (
//     <header>
//       <nav className={styles.navbarContainer} ref={dropdownRef}>
//         <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
//           <button
//             className={styles.menuBtn}
//             onClick={toggleMenu}
//             aria-expanded={isOpen}
//             style={{ display: 'flex', alignItems: 'center', gap: 8 }}
//           >
//             <svg
//               width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
//             >
//               {isOpen ? (
//                 <path d="M18 6L6 18M6 6l12 12" />
//               ) : (
//                 <path d="M3 12h18M3 6h18M3 18h18" />
//               )}
//             </svg>
//             <span>Menu</span>
//           </button>
//           {/* Dark/Light mode toggle button */}
//           <button
//             className={styles.menuBtn}
//             style={{ display: 'flex', alignItems: 'center', gap: 8 }}
//             onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
//             aria-label="Toggle dark/light mode"
//           >
//             {theme === 'light' ? (
//               <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="5" /><path d="M12 1v2m0 18v2m11-11h-2M3 12H1m16.95 6.95-1.41-1.41M6.46 6.46 5.05 5.05m12.02 0-1.41 1.41M6.46 17.54l-1.41 1.41" /></svg>
//             ) : (
//               <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3a7 7 0 0 0 9.79 9.79z" /></svg>
//             )}
//             <span>{theme === 'light' ? 'Sáng' : 'Tối'}</span>
//           </button>
//         </div>
//         <div className={isOpen ? `${styles.dropdown} ${styles.active}` : styles.dropdown}>
//           <div className={styles.menuItem}>
//             {/* Đã bỏ liên kết Trang chủ */}
//           </div>
//           <div className={styles.menuItem}>
//             <Link href="/chat">
//               <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
//                 <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
//                 <polyline points="14 2 14 8 20 8"></polyline>
//                 <line x1="16" y1="13" x2="8" y2="13"></line>
//                 <line x1="16" y1="17" x2="8" y2="17"></line>
//                 <polyline points="10 9 9 9 8 9"></polyline>
//               </svg>
//               <span className="iconWrapper">
//                 truy vấn dữ liệu
//               </span>
//             </Link>
//           </div>
//           <div className={styles.menuItem}>
//             <Link href="/create-contract">
//               <span className="iconWrapper">
//                 <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
//                   <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
//                   <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
//                 </svg>
//               </span>
//               Tạo Hợp Đồng
//             </Link>
//           </div>
//         </div>
//       </nav>
//     </header>
//   );
// }

// export default Navbar;
