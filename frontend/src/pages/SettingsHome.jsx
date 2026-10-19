import React from 'react';
import { useSearchParams } from 'react-router-dom';
import Settings from './Settings';
import AiLimits from './AiLimits';

// Stub: the redesign rebuilds Settings later. Until then the current page
// serves /settings, and ?tab=limits (guardrails + autopilot limits) serves AiLimits.
const SettingsHome = () => {
  const [params] = useSearchParams();
  return params.get('tab') === 'limits' ? <AiLimits /> : <Settings />;
};

export default SettingsHome;
