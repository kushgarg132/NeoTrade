import React from 'react';
import { ModelSheet, UsageSheet } from './Models';

/** The AI model page: model choice, plus usage for admins. */
const AiModel = ({ isAdmin }) => (
  <>
    <ModelSheet isAdmin={isAdmin} />
    {isAdmin && <UsageSheet />}
  </>
);

export default AiModel;
