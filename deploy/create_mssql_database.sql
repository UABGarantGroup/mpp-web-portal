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
IF NOT EXISTS (SELECT name FROM sys.databases WHERE name = N'Garant_MPP_hub')
BEGIN
    PRINT 'Creating database [Garant_MPP_hub]...';
    CREATE DATABASE [Garant_MPP_hub]
    COLLATE Latin1_General_100_CI_AS_SC_UTF8; -- Recommended UTF-8 collation; falls back to server default if UTF-8 not supported
END
ELSE
BEGIN
    PRINT 'Database [Garant_MPP_hub] already exists.';
END
GO

-- 2. Configure Snapshot Isolation for High Concurrency
-- Prevents readers and writers from blocking each other in enterprise environments
ALTER DATABASE [Garant_MPP_hub] SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE;
ALTER DATABASE [Garant_MPP_hub] SET ALLOW_SNAPSHOT_ISOLATION ON;
ALTER DATABASE [Garant_MPP_hub] SET AUTO_UPDATE_STATISTICS ON;
ALTER DATABASE [Garant_MPP_hub] SET AUTO_CLOSE OFF;
GO

PRINT 'Database [Garant_MPP_hub] configuration updated successfully.';
GO

-- ==============================================================================
-- Application Login and User: garantMPPadmin
-- ==============================================================================
IF NOT EXISTS (SELECT name FROM sys.server_principals WHERE name = N'garantMPPadmin')
BEGIN
    PRINT 'Creating login [garantMPPadmin]...';
    CREATE LOGIN [garantMPPadmin] WITH PASSWORD = N'.c?6j1R!G$g;tYT9M#Sy', CHECK_POLICY = ON;
END
GO

USE [Garant_MPP_hub];
GO

IF NOT EXISTS (SELECT name FROM sys.database_principals WHERE name = N'garantMPPadmin')
BEGIN
    PRINT 'Creating user [garantMPPadmin] in [Garant_MPP_hub]...';
    CREATE USER [garantMPPadmin] FOR LOGIN [garantMPPadmin];
    ALTER ROLE [db_owner] ADD MEMBER [garantMPPadmin];
    PRINT 'User [garantMPPadmin] mapped and granted db_owner permissions on [Garant_MPP_hub].';
END
GO

