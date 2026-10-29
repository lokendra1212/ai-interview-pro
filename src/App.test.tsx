// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import App from './App';

afterEach(() => { cleanup(); sessionStorage.clear(); });

describe('AI Interview Pro sign-in screen', () => {
  it('shows the sign-in form and switches to account creation', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: /sign in to your workspace/i })).toBeTruthy();
    screen.getByRole('button', { name: 'Create account' }).click();
    expect(await screen.findByRole('heading', { name: /create your account/i })).toBeTruthy();
    expect(screen.getByLabelText(/your name/i)).toBeTruthy();
  });
});
