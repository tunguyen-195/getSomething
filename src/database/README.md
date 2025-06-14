# Database Management

This directory contains the database models and management scripts for the Speech to Information system.

## Database Structure

### Core Tables

#### Users and Authentication
- `User`: Stores user information and authentication details
  - Basic info: username, email, password_hash, full_name
  - Status: is_active, last_login
  - Relationships: role, cases, audio_files
  - Security: password_hash uses bcrypt encryption

- `UserRole`: Defines user roles and permissions
  - Role types: admin, user
  - Permissions stored as JSON for flexibility
  - Hierarchical permission system

#### Case Management
- `Case`: Main case information
  - Basic info: case_code, title, description
  - Status tracking: status_id, priority_id
  - Timestamps: created_at, closed_at
  - Relationships: participants, audio_files, notes

- `CaseStatus`: Case status definitions
  - Status types: active, closed, pending
  - Status metadata: description, is_active

- `CasePriority`: Case priority levels
  - Priority levels: high, medium, low
  - Weight system for sorting

- `CaseParticipant`: Case-user relationships
  - Role assignment
  - Permission tracking
  - Audit trail

#### Audio Processing
- `AudioFile`: Audio file metadata and storage management
  - File info: name, path, size, duration
  - Processing status: status_id, processed_at
  - Error handling: error_message
  - Storage management: storage_type, storage_config
  - Archive support: is_archived, archive_reason
  - File operations: archive, restore, delete
  - Storage path management
  - Relationships: case, language, status

- `Transcription`: Speech-to-text results
  - Version control
  - Language tracking
  - Content storage
  - Audit trail

- `AnalysisResult`: Context analysis results
  - Version control
  - Summary and sentiment
  - Detailed analysis
  - Audit trail

#### Supporting Tables
- `Language`: Supported languages
- `AudioStatus`: Audio processing states
- `Sentiment`: Sentiment analysis results
- `ActivityLog`: System activity tracking
- `ActivityType`: Activity categorization

### File Storage Strategy

#### Local Storage
- Audio files are stored in the filesystem, not in the database
- Base directory: `storage/audio/` (configurable via AUDIO_STORAGE_ROOT)
- Directory structure:
  ```
  storage/audio/
  ├── cases/
  │   └── {case_id}/
  │       └── {audio_files}
  └── archive/
      └── {audio_id}/
          └── {archived_files}
  ```

#### Storage Features
1. **Organization**
   - Files organized by case
   - Separate archive directory
   - Unique file paths

2. **File Management**
   - Automatic directory creation
   - File existence checking
   - Path resolution
   - Archive/restore support

3. **Storage Types**
   - Local filesystem (default)
   - S3 support (configurable)
   - Extensible for other storage backends

4. **Security**
   - Path validation
   - Access control
   - File operations logging

### Key Features

1. **Version Control**
   - All major entities support versioning
   - Tracks changes over time
   - Maintains history

2. **Audit Trail**
   - Comprehensive activity logging
   - User action tracking
   - Change history

3. **Security**
   - Role-based access control
   - Permission management
   - Sensitive data handling

4. **Performance**
   - Indexed fields for common queries
   - Optimized relationships
   - Efficient data retrieval
   - File system for large files

## Database Rules

### Naming Conventions
- Table names: lowercase, plural
- Column names: lowercase, underscore
- Foreign keys: table_name_id
- Timestamps: created_at, updated_at

### Data Integrity
1. **Required Fields**
   - All tables have id, created_at, updated_at
   - Core fields marked as nullable=False
   - Unique constraints where appropriate

2. **Relationships**
   - Foreign key constraints
   - Cascade delete where appropriate
   - Many-to-many through junction tables

3. **Data Validation**
   - Field length limits
   - Data type constraints
   - Enum values for status/type fields

### Security Rules
1. **Access Control**
   - Role-based permissions
   - Resource-level access
   - Audit logging

2. **Data Protection**
   - Password encryption
   - Sensitive data marking
   - Access logging

## Setup and Maintenance

### Initial Setup
1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure environment:
```bash
# Create .env file
POSTGRES_USER=your_username
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=speech_to_info
AUDIO_STORAGE_ROOT=/path/to/audio/storage
```

3. Initialize database:
```bash
# Create database
createdb speech_to_info

# Run migrations
alembic upgrade head

# Initialize with initial data
python -m src.database.scripts.init_db
```

### Regular Maintenance
1. **Backup Schedule**
   - Daily full backups
   - Weekly archive backups
   - Monthly retention policy

2. **Performance Monitoring**
   - Query performance tracking
   - Index usage analysis
   - Connection pool monitoring
   - Storage space monitoring

3. **Data Cleanup**
   - Archive old records
   - Clean temporary files
   - Maintain audit logs
   - Clean up unused audio files

### Backup and Restore
```bash
# Backup database
pg_dump -U your_username speech_to_info > backup.sql

# Backup audio files
tar -czf audio_backup.tar.gz storage/audio/

# Restore database
psql -U your_username speech_to_info < backup.sql

# Restore audio files
tar -xzf audio_backup.tar.gz
```

## Optimization Guidelines

### Indexing Strategy
1. **Primary Keys**
   - All tables use integer primary keys
   - Auto-incrementing sequences

2. **Foreign Keys**
   - Indexed for relationship queries
   - Optimized for joins

3. **Search Fields**
   - Full-text search indexes
   - Case-insensitive searches
   - Pattern matching optimization

### Query Optimization
1. **Common Queries**
   - Optimized for frequent operations
   - Cached results where appropriate
   - Efficient joins

2. **Batch Operations**
   - Bulk insert optimization
   - Batch update handling
   - Efficient deletion

### Performance Tuning
1. **Connection Pool**
   - Configured for optimal size
   - Connection timeout handling
   - Resource cleanup

2. **Query Cache**
   - Frequently accessed data
   - Cache invalidation
   - Memory management

3. **File System**
   - Regular cleanup
   - Storage monitoring
   - Access pattern optimization

## Development Guidelines

### Adding New Features
1. **Schema Changes**
   - Create new migration
   - Update models
   - Test changes

2. **Data Updates**
   - Use migrations for data
   - Version control changes
   - Test data integrity

### Best Practices
1. **Code Organization**
   - Modular design
   - Clear separation of concerns
   - Consistent patterns

2. **Testing**
   - Unit tests for models
   - Integration tests
   - Performance testing
   - File system testing

3. **Documentation**
   - Keep README updated
   - Document changes
   - Maintain examples

## Troubleshooting

### Common Issues
1. **Connection Problems**
   - Check credentials
   - Verify network
   - Check firewall

2. **Performance Issues**
   - Monitor slow queries
   - Check indexes
   - Analyze execution plans
   - Check storage space

3. **Data Integrity**
   - Verify constraints
   - Check relationships
   - Validate data
   - Check file existence

### Support
For database issues:
1. Check logs
2. Review documentation
3. Contact system administrator 