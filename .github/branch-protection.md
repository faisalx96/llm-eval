# Branch Protection Configuration

This document outlines the recommended branch protection rules for the LLM-Eval repository to ensure code quality and prevent direct pushes to important branches.

## Main Branch Protection Rules

Configure the following settings for the `main` branch in your GitHub repository settings:

### Required Status Checks
Enable "Require status checks to pass before merging" with the following checks:

**Backend Quality Gates:**
- `Code Quality` (lint-and-format job)
- `Test Suite` (test-matrix job)
- `Export Format Validation` (export-validation job)
- `CLI Integration Tests` (cli-integration job)
- `Security Scan` (security-scan job)

**Frontend Quality Gates:**
- `Frontend Code Quality` (frontend-quality job)
- `Frontend Tests` (frontend-tests job)

**Overall Quality:**
- `Quality Gates` (quality-gates job)

### Additional Settings

1. **Require branches to be up to date before merging**: ✅ Enabled
   - Ensures PRs are tested against the latest main branch

2. **Require review from code owners**: ✅ Enabled
   - At least 1 approval required
   - Dismiss stale reviews when new commits are pushed

3. **Restrict pushes that create files**: ✅ Enabled
   - Prevents direct pushes to main branch
   - All changes must go through pull requests

4. **Allow force pushes**: ❌ Disabled
   - Prevents history rewriting on main branch

5. **Allow deletions**: ❌ Disabled
   - Prevents accidental branch deletion

## Development Branch Protection (Optional)

For `develop` branch (if using GitFlow):

### Required Status Checks
- `Code Quality` (lint-and-format job)
- `Test Suite` (test-matrix job)
- `Frontend Code Quality` (frontend-quality job)
- `Frontend Tests` (frontend-tests job)

### Settings
- Require pull request reviews: 1 approval
- Require branches to be up to date: ✅ Enabled
- Allow force pushes: ❌ Disabled

## CODEOWNERS File

Create a `.github/CODEOWNERS` file to automatically assign reviewers:

```
# Global owners
* @faisalx96

# Backend code
llm_eval/ @faisalx96
tests/ @faisalx96
setup.py @faisalx96

# Frontend code
frontend/ @faisalx96

# CI/CD configuration
.github/ @faisalx96
.pre-commit-config.yaml @faisalx96

# Documentation
docs/ @faisalx96
*.md @faisalx96
```

## Auto-merge Conditions

Consider enabling auto-merge for PRs that meet these criteria:
- All status checks pass
- Required reviews approved
- No changes requested
- Author is a maintainer
- PR is not a draft

## Security Considerations

1. **Enable vulnerability alerts**: ✅
2. **Enable automated security updates**: ✅ 
3. **Require signed commits**: Consider enabling for enhanced security
4. **Enable secret scanning**: ✅ (via CodeQL workflow)
5. **Enable dependency review**: ✅ (via CodeQL workflow)

## Workflow Configuration

The CI/CD pipelines are designed to support these branch protection rules:

### Fast Feedback Loop
- Linting and basic checks run first (< 2 minutes)
- Comprehensive test suite runs in parallel
- Frontend and backend validated simultaneously

### Performance Optimizations
- Dependency caching reduces build time
- Matrix builds run in parallel
- Optional dependency tests run separately

### Quality Gates
- Multiple validation layers ensure code quality
- Export format validation prevents breaking changes
- CLI integration tests verify user experience

## Manual Override Process

In emergency situations, maintainers can:

1. **Temporarily disable branch protection**
   - Only for critical hotfixes
   - Must be re-enabled immediately after merge

2. **Use admin override**
   - Available to repository administrators
   - Should be used sparingly and documented

3. **Emergency deployment process**
   - Direct push allowed only for security patches
   - Must create follow-up PR to restore protection

## Monitoring and Alerts

Set up notifications for:
- Failed CI/CD pipeline runs
- Security vulnerability discoveries
- Branch protection rule changes
- Failed deployments

## Regular Review Process

1. **Monthly review of protection rules**
   - Assess if rules are appropriate
   - Update based on team feedback

2. **Quarterly security audit**
   - Review CODEOWNERS assignments
   - Validate secret scanning effectiveness
   - Check dependency vulnerability status

3. **Annual process evaluation**
   - Measure impact on development velocity
   - Assess quality improvements
   - Update documentation and processes