import React from 'react';
import styles from '../styles/UploadProgress.module.css';

const UploadProgress = ({ percent, fileName, status }) => {
  if (percent === null && status !== 'attaching') return null;

  return (
    <div className={styles.progressToast}>
      <div className={styles.progressInfo}>
        <span className={styles.fileName}>{fileName || 'Đang xử lý...'}</span>
        <span className={styles.percent}>{status === 'attaching' ? 'Đang đính kèm...' : `${percent}%`}</span>
      </div>
      <div className={styles.progressBarContainer}>
        <div 
          className={`${styles.progressBar} ${status === 'attaching' ? styles.indeterminate : ''}`} 
          style={{ width: status === 'attaching' ? '100%' : `${percent}%` }}
        ></div>
      </div>
    </div>
  );
};

export default UploadProgress;
