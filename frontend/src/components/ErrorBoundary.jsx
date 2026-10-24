import React from 'react';
import Empty from './ui/Empty';
import Button from './ui/Button';

/**
 * A crash in one page (a data shape the frontend didn't expect, a bad API
 * response) currently white-screens the whole app -- there was no error
 * boundary anywhere in the tree. This catches at the page level so one
 * broken section degrades to a message instead of a blank sheet.
 */
class ErrorBoundary extends React.Component {
  state = { error: null };

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('Uncaught error in page tree:', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <Empty
          title="This part of the page didn't load"
          body="Some data came back in a shape the page didn't expect. Reload to try again; the rest of the app still works."
          action={<Button variant="secondary" onClick={() => window.location.reload()}>Reload</Button>}
        />
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
