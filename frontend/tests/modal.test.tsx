import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { Modal } from '@/components/ui';

describe('form modal dismissal', () => {
  it('ignores dialog-surface clicks and a click retargeted from an input drag', () => {
    const close = vi.fn();
    render(<Modal title="Edit record" onClose={close}><input aria-label="Draft" defaultValue="Unsaved input" /></Modal>);
    const dialog = screen.getByRole('dialog');
    const input = screen.getByRole('textbox', { name: 'Draft' });
    fireEvent.click(dialog);
    fireEvent.mouseDown(input);
    fireEvent.mouseUp(dialog);
    fireEvent.click(dialog);
    expect(close).not.toHaveBeenCalled();
    expect(input).toHaveValue('Unsaved input');
    expect(dialog).toHaveAttribute('open');
    fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(close).toHaveBeenCalledOnce();
  });

  it('retains the standard Escape/cancel dismissal request', () => {
    const close = vi.fn();
    render(<Modal title="Edit record" onClose={close}><input aria-label="Draft" /></Modal>);
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }));
    expect(close).toHaveBeenCalledOnce();
  });
});
