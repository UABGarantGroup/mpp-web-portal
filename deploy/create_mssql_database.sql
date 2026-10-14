-- ==============================================================================
-- MS Project Centralized Resource & Template Hub (mpp-web-portal)
-- Microsoft SQL Server Database Creation & Configuration Script
-- ==============================================================================
-- Instructions:
-- 1. Open this script in SQL Server Management Studio (SSMS) or Azure Data Studio.
-- 2. Connect to your MS SQL Server instance with administrative privileges (e.g., 'sa' or sysadmin).
-- 3. Execute the script (press F5).
-- ==============================================================================

USE [master];
GO

-- 1. Create database if it does not already exist
IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'mpp_hub')
BEGIN
    PRINT 'Creating database [mpp_hub]...';
    CREATE DATABASE [mpp_hub]
    COLLATE Latin1_General_100_CI_AS_SC_UTF8; -- Recommended UTF-8 collation; falls back to server default if UTF-8 not supported
END
ELSE
BEGIN
    PRINT 'Database [mpp_hub] already exists.';
END
GO

-- 2. Configure Snapshot Isolation for High Concurrency
-- Prevents readers and writers from blocking each other in enterprise environments
ALTER DATABASE [mpp_hub] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
ALTER DATABASE [mpp_hub] SET ALLOW_SNAPSHOT_ISOLATION ON;
ALTER DATABASE [mpp_hub] SET AUTO_UPDATE_STATISTICS ON;
ALTER DATABASE [mpp_hub] SET AUTO_CLOSE OFF;
GO

PRINT 'Database [mpp_hub] configuration updated successfully.';
GO

-- ==============================================================================
-- OPTIONAL: Create Dedicated Application Login and User
-- (Uncomment and adjust username / password if not using 'sa' or Windows Auth)
-- ==============================================================================
/*
IF NOT EXISTS (SELECT name FROM sys.server_principals WHERE name = N'mpp_user')
BEGIN
    PRINT 'Creating login [mpp_user]...';
    CREATE LOGIN [mpp_user] WITH PASSWORD = N'YourStrongPasswordHere!2026', CHECK_POLICY = ON;
END
GO

USE [mpp_hub];
GO

IF NOT EXISTS (SELECT name FROM sys.database_principals WHERE name = N'mpp_user')
BEGIN
    PRINT 'Creating user [mpp_user] in [mpp_hub]...';
    CREATE USER [mpp_user] FOR LOGIN [mpp_user];
    ALTER ROLE [db_owner] ADD MEMBER [mpp_user];
    PRINT 'User [mpp_user] mapped and granted db_owner permissions on [mpp_hub].';
END
GO
*/
