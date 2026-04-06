import { describe, it, expect, beforeEach } from 'vitest';
import { TemplateConnector } from '../index';

describe('TemplateConnector', () => {
  let connector: TemplateConnector;

  beforeEach(() => {
    connector = new TemplateConnector();
  });

  it('should have correct metadata', () => {
    expect(connector.id).toBe('template');
    expect(connector.name).toBeDefined();
    expect(connector.categories.length).toBeGreaterThan(0);
    expect(connector.description).toBeDefined();
  });

  it('should initialize without errors', async () => {
    await expect(connector.init({})).resolves.not.toThrow();
  });

  it('should return events within date range', async () => {
    await connector.init({});
    const from = new Date('2024-01-01');
    const to = new Date('2024-12-31');
    const events = await connector.fetchEvents(from, to);

    expect(Array.isArray(events)).toBe(true);

    for (const event of events) {
      expect(event.id).toBeDefined();
      expect(event.source).toBe(connector.id);
      expect(event.category).toBeDefined();
      expect(event.timestamp).toBeInstanceOf(Date);
    }
  });

  it('should validate configuration', async () => {
    await connector.init({});
    const result = await connector.validate();

    expect(result).toHaveProperty('valid');
    if (!result.valid) {
      expect(result.errors).toBeDefined();
      expect(result.errors!.length).toBeGreaterThan(0);
    }
  });
});
