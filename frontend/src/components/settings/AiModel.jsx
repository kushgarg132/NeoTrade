import React from 'react';
import { ModelSheet, UsageSheet, GeminiUsageSheet } from './Models';

/** The AI model page: model choice, plus usage for admins. */
const AiModel = ({ isAdmin }) => (
  <>
    <ModelSheet isAdmin={isAdmin} />
    {isAdmin && <UsageSheet />}
    {isAdmin && <GeminiUsageSheet />}
  </>
);

export default AiModel;
