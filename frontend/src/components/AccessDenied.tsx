/**
 * Access-denied page shown when a user lacks the required role for an action
 * or route (403 response from the backend).
 *
 * Contract: PHASE_5_0_AUTH_API_CONTRACT.md Section 5 (403 handling).
 */

import React from 'react';
import { IconShieldCheck } from './icons';

interface AccessDeniedProps {
  requiredRole?: string;
  onBack?: () => void;
}

export const AccessDenied: React.FC<AccessDeniedProps> = ({
  requiredRole,
  onBack,
}) => {
  return (
    <div className="access-denied-page">
      <div className="access-denied-card">
        <div className="access-denied-icon">
          <IconShieldCheck size={36} />
        </div>
        <h1 className="access-denied-title">Access denied</h1>
        <p className="access-denied-message">
          {requiredRole
            ? `This area requires the ${requiredRole.toUpperCase()} role. Your account does not have permission to access it.`
            : 'You do not have permission to perform this action.'}
        </p>
        <p className="access-denied-note">
          Frontend permissions improve usability, but backend authorization
          remains the security boundary. Contact your administrator if you
          believe you should have access.
        </p>
        <div className="access-denied-actions">
          {onBack && (
            <button className="btn-secondary" onClick={onBack}>
              Go back
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default AccessDenied;
