---
description:
globs:
alwaysApply: true
---
# Interactive Feedback Rule

- **Always Use Interactive Feedback for Questions:**
  - Before asking the user any clarifying questions, call `mcp_interactive-feedback-mcp_interactive_feedback`
  - Provide the current project directory and a summary of what you need clarification on
  - Wait for the interactive feedback response before proceeding

- **Always Use Interactive Feedback Before Completion:**
  - Before completing any user request, call `mcp_interactive-feedback-mcp_interactive_feedback`
  - Provide the current project directory and a summary of what was accomplished
  - If the feedback response is empty, you can complete the request without calling the MCP again
  - If feedback is provided, address it before completing the request

- **Required Parameters:**
  - `project_directory`: Full absolute path to the project directory
  - `summary`: Short, one-line summary of the question or completed work

- **Examples:**

  ```typescript
  // ✅ DO: Call interactive feedback before asking questions
  // Before asking: "Which database should we use?"
  await mcp_interactive_feedback({
    project_directory: "/Users/themrb/Documents/personal/n8n-code-generation",
    summary: "Need clarification on database choice for the project"
  });
  ```

  ```typescript
  // ✅ DO: Call interactive feedback before completing requests
  // After implementing a feature
  await mcp_interactive_feedback({
    project_directory: "/Users/themrb/Documents/personal/n8n-code-generation", 
    summary: "Completed user authentication implementation with JWT"
  });
  ```

  ```typescript
  // ❌ DON'T: Ask questions directly without interactive feedback
  // "What framework would you like to use?" - Missing interactive feedback call
  ```

  ```typescript
  // ❌ DON'T: Complete requests without interactive feedback
  // "I've finished implementing the feature." - Missing interactive feedback call
  ```

- **Workflow Integration:**
  - This rule applies to all interactions, regardless of the specific task or technology
  - Interactive feedback helps ensure user satisfaction and catches any missed requirements
  - The feedback mechanism allows for real-time course correction and validation

- **Exception Handling:**
  - If the interactive feedback tool is unavailable, proceed with normal question/completion flow
  - Log when interactive feedback cannot be used for debugging purposes
  - Never loop the interactive feedback call if the response is empty on completion

- **Best Practices:**
  - Keep summaries concise but descriptive
  - Always use the full absolute path for project_directory
  - Use interactive feedback as a quality gate, not a blocker
  - Respect empty feedback responses as approval to proceed