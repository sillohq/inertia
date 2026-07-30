# Release Guide for Sillo Inertia

This document outlines the process for releasing Sillo Inertia versions.

---

## 🚀 Release Process

### Prerequisites
- All tests passing: `cd inertia && uv run pytest tests/`
- All changes committed to git
- CHANGELOG.md updated with release notes
- Version number set in `pyproject.toml`

### Tag Format
```
inertia-v<VERSION>

Examples:
- inertia-v0.1.0  (stable)
- inertia-v0.1.1  (patch)
- inertia-v0.2.0a1 (alpha)
- inertia-v0.2.0b1 (beta)
```

### Step-by-Step Release

#### 1. Update CHANGELOG
Edit `inertia/CHANGELOG.md` with release notes:
```markdown
## [0.1.1] - 2026-07-31

### Fixed
- Bug fix 1
- Bug fix 2
```

#### 2. Update Version
Edit `inertia/pyproject.toml`:
```toml
[project]
version = "0.1.1"
```

#### 3. Commit Changes
```bash
git add inertia/CHANGELOG.md inertia/pyproject.toml
git commit -m "Release: Inertia v0.1.1"
```

#### 4. Create Git Tag
```bash
# Create annotated tag
git tag inertia-v0.1.1 -m "Sillo Inertia v0.1.1"

# Verify tag created
git tag -l 'inertia-v*'
```

#### 5. Push to GitHub
```bash
# Push commits
git push origin main

# Push tag (triggers CI/CD release)
git push origin inertia-v0.1.1
```

### Automatic Release Process
Once the tag is pushed, GitHub Actions will automatically:
1. ✅ Check out the code
2. ✅ Run all tests (must pass)
3. ✅ Build the package
4. ✅ Publish to PyPI

---

## 📋 Release Checklist

### Before Release
- [ ] All tests passing: `cd inertia && uv run pytest tests/`
- [ ] No uncommitted changes: `git status`
- [ ] Latest code pulled: `git pull origin main`
- [ ] CHANGELOG.md updated with release notes
- [ ] Version number updated in `pyproject.toml`
- [ ] Changes committed: `git commit -m "Release: v0.1.1"`

### During Release
- [ ] Create tag: `git tag inertia-v0.1.1 -m "..."`
- [ ] Verify tag: `git tag -l 'inertia-v*'`
- [ ] Push tag: `git push origin inertia-v0.1.1`

### After Release
- [ ] Check GitHub Actions: https://github.com/sillohq/inertia/actions
- [ ] Wait for CI/CD to complete (5-10 minutes)
- [ ] Verify PyPI release: https://pypi.org/project/sillo-inertia/
- [ ] Test installation: `pip install --upgrade sillo-inertia`

---

## 🔍 Verifying Release

### Check PyPI
```bash
# Search PyPI
pip index versions sillo-inertia

# Install latest
pip install --upgrade sillo-inertia

# Verify version
python -c "import sillo_inertia; print(sillo_inertia.__version__)" 2>/dev/null || echo "No __version__ in package"
```

### Check GitHub Releases
Visit: https://github.com/sillohq/inertia/releases/tag/inertia-v0.1.1

---

## ⚡ Quick Release (0.1.1 example)

```bash
# 1. Update changelog and commit
git add inertia/CHANGELOG.md inertia/pyproject.toml
git commit -m "Release: Inertia v0.1.1"

# 2. Create and push tag
git tag inertia-v0.1.1 -m "Sillo Inertia v0.1.1"
git push origin main
git push origin inertia-v0.1.1

# 3. Monitor CI/CD
open https://github.com/sillohq/inertia/actions

# 4. Verify release
pip install --upgrade sillo-inertia
```

---

## 📦 PyPI Credentials

The release uses **GitHub OIDC Trusted Publishing**, which requires:
1. GitHub: PYPI_TOKEN secret configured (already done)
2. PyPI: OIDC provider linked to sillohq/inertia repository (already done)

No manual PyPI login needed!

---

## 🔄 Post-Release

### Announce Release
- Post on Twitter/Bluesky
- Update documentation site
- Create GitHub Discussions post

---

## 🐛 Hotfix Releases

If a critical bug is found in 0.1.0:

```bash
# 1. Create hotfix branch from tag
git checkout -b hotfix/v0.1.1 inertia-v0.1.0

# 2. Fix the bug, commit
git commit -m "Fix: critical bug in v0.1.0"

# 3. Update version to 0.1.1
# 4. Update CHANGELOG
# 5. Create tag and push
git tag inertia-v0.1.1 -m "Sillo Inertia v0.1.1 - Hotfix"
git push origin hotfix/v0.1.1
git push origin inertia-v0.1.1

# 6. Merge back to main
git checkout main
git pull origin main
git merge hotfix/v0.1.1
git push origin main
```

---

## 🎯 Version Strategy

**Sillo Inertia uses Semantic Versioning:**

- `0.1.0` - Initial stable release
- `0.1.1` - Bug fixes
- `0.2.0` - New features
- `1.0.0` - First major stable release

---

## 🚨 Troubleshooting

### "Tag already exists"
```bash
# Delete local tag
git tag -d inertia-v0.1.1

# Delete remote tag (careful!)
git push origin --delete inertia-v0.1.1

# Recreate tag
git tag inertia-v0.1.1 -m "..."
git push origin inertia-v0.1.1
```

### "Tests failed in CI/CD"
1. Check GitHub Actions logs
2. Fix the issue locally
3. Commit and push to main
4. Delete the failed tag
5. Create new tag once main is fixed

### "PyPI publish failed"
Check:
1. PYPI_TOKEN secret is set
2. PyPI OIDC provider is linked
3. Package version matches tag
4. No version conflicts on PyPI

Contact: https://github.com/sillohq/inertia/issues

---

## 📞 Support

For release issues, open an issue on GitHub:
https://github.com/sillohq/inertia/issues

Tag: `[release]`
