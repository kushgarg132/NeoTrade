import React from 'react';
import GuardrailsSheet from '../journal/GuardrailsSheet';
import PortfolioReview from './PortfolioReview';
import AutopilotSheet from './AutopilotSheet';
import EngineSettings from '../paper/EngineSettings';

/** Your own guardrails and portfolio limits; admins also get the autopilot and engine limits (was AiLimits). */
const Limits = ({ isAdmin }) => (
  <div className="space-y-3">
    <GuardrailsSheet />
    <PortfolioReview isAdmin={isAdmin} />
    {isAdmin && <AutopilotSheet />}
    {isAdmin && <EngineSettings />}
  </div>
);

export default Limits;
