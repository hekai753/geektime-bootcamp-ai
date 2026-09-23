-- ============================================================================
-- MySQL Small Database: Blog System (blog_small)
-- ============================================================================
-- Description: MySQL port of 01_small_db.sql for multi-database testing
-- Tables: 7 | Views: 3 | Indexes: 12
-- Load with:
--   mysql -h <host> -u <user> -p < 04_mysql_blog.sql
-- ============================================================================

DROP DATABASE IF EXISTS blog_small;
CREATE DATABASE blog_small CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE blog_small;

-- ============================================================================
-- TABLES
-- ============================================================================

CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    role ENUM('admin', 'author', 'reader') DEFAULT 'reader',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) COMMENT='Blog users with roles';

CREATE TABLE categories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) COMMENT='Blog post categories';

CREATE TABLE posts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    slug VARCHAR(200) UNIQUE NOT NULL,
    content TEXT NOT NULL,
    excerpt TEXT,
    author_id INT NOT NULL,
    category_id INT NULL,
    status ENUM('draft', 'published', 'archived') DEFAULT 'draft' COMMENT 'Post publication status',
    view_count INT DEFAULT 0,
    published_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_posts_author FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_posts_category FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
) COMMENT='Blog posts with authors and categories';

CREATE TABLE tags (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    slug VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) COMMENT='Tags for categorizing posts';

CREATE TABLE post_tags (
    post_id INT NOT NULL,
    tag_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (post_id, tag_id),
    CONSTRAINT fk_post_tags_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    CONSTRAINT fk_post_tags_tag FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
) COMMENT='Many-to-many relationship between posts and tags';

CREATE TABLE comments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    post_id INT NOT NULL,
    user_id INT NOT NULL,
    parent_id INT NULL COMMENT 'Parent comment ID for nested replies',
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_comments_post FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
    CONSTRAINT fk_comments_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    CONSTRAINT fk_comments_parent FOREIGN KEY (parent_id) REFERENCES comments(id) ON DELETE CASCADE
) COMMENT='User comments on posts with threading support';

CREATE TABLE user_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    login_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    logout_time TIMESTAMP NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) COMMENT='User login session tracking';

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX idx_users_role ON users(role);
CREATE INDEX idx_users_created_at ON users(created_at);
CREATE INDEX idx_posts_author_id ON posts(author_id);
CREATE INDEX idx_posts_category_id ON posts(category_id);
CREATE INDEX idx_posts_status ON posts(status);
CREATE INDEX idx_posts_published_at ON posts(published_at);
CREATE INDEX idx_posts_created_at ON posts(created_at);
CREATE INDEX idx_comments_post_id ON comments(post_id);
CREATE INDEX idx_comments_user_id ON comments(user_id);
CREATE INDEX idx_comments_parent_id ON comments(parent_id);
CREATE INDEX idx_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_sessions_login_time ON user_sessions(login_time);

-- ============================================================================
-- VIEWS
-- ============================================================================

CREATE VIEW published_posts AS
SELECT p.id, p.title, p.slug, u.username AS author, c.name AS category, p.published_at, p.view_count
FROM posts p
JOIN users u ON p.author_id = u.id
LEFT JOIN categories c ON p.category_id = c.id
WHERE p.status = 'published';

CREATE VIEW user_stats AS
SELECT u.id, u.username, u.full_name, u.role,
       COUNT(DISTINCT p.id) AS post_count,
       COUNT(DISTINCT c.id) AS comment_count
FROM users u
LEFT JOIN posts p ON u.id = p.author_id
LEFT JOIN comments c ON u.id = c.user_id
GROUP BY u.id, u.username, u.full_name, u.role;

CREATE VIEW popular_tags AS
SELECT t.id, t.name, COUNT(pt.post_id) AS usage_count
FROM tags t
LEFT JOIN post_tags pt ON t.id = pt.tag_id
GROUP BY t.id, t.name
ORDER BY usage_count DESC;

-- ============================================================================
-- SEED DATA
-- ============================================================================

INSERT INTO users (username, email, full_name, role) VALUES
('admin', 'admin@blog.com', 'Admin User', 'admin'),
('alice', 'alice@blog.com', 'Alice Johnson', 'author'),
('bob', 'bob@blog.com', 'Bob Smith', 'author'),
('charlie', 'charlie@blog.com', 'Charlie Brown', 'reader'),
('diana', 'diana@blog.com', 'Diana Prince', 'reader'),
('evan', 'evan@blog.com', 'Evan Williams', 'reader'),
('frank', 'frank@blog.com', 'Frank Miller', 'author'),
('grace', 'grace@blog.com', 'Grace Hopper', 'reader');

INSERT INTO categories (name, slug, description) VALUES
('Technology', 'technology', 'Articles about technology and programming'),
('Travel', 'travel', 'Travel guides and experiences'),
('Food', 'food', 'Recipes and restaurant reviews'),
('Lifestyle', 'lifestyle', 'Life tips and personal development'),
('Business', 'business', 'Business insights and entrepreneurship');

INSERT INTO tags (name, slug) VALUES
('Python', 'python'),
('JavaScript', 'javascript'),
('Tutorial', 'tutorial'),
('Review', 'review'),
('Guide', 'guide'),
('Opinion', 'opinion'),
('News', 'news'),
('Tips', 'tips');

INSERT INTO posts (title, slug, content, excerpt, author_id, category_id, status, view_count, published_at) VALUES
('Getting Started with Python', 'getting-started-with-python',
 'Python is a versatile programming language...',
 'Learn the basics of Python programming',
 2, 1, 'published', 1523, NOW() - INTERVAL 30 DAY),
('Top 10 Travel Destinations', 'top-10-travel-destinations',
 'From Tokyo to Paris, these destinations...',
 'The best places to visit this year',
 3, 2, 'published', 987, NOW() - INTERVAL 25 DAY),
('Homemade Pizza Guide', 'homemade-pizza-guide',
 'Making pizza at home is easier than...',
 'Master homemade pizza in 5 steps',
 2, 3, 'published', 745, NOW() - INTERVAL 20 DAY),
('Productivity Tips for Developers', 'productivity-tips-for-developers',
 'Stay focused and ship more code...',
 'Boost your daily productivity',
 4, 4, 'published', 612, NOW() - INTERVAL 15 DAY),
('Startup Lessons Learned', 'startup-lessons-learned',
 'After 5 years of building startups...',
 'What I learned founding three companies',
 7, 5, 'published', 434, NOW() - INTERVAL 10 DAY),
('Modern JavaScript Features', 'modern-javascript-features',
 'ES6+ brought powerful features...',
 'Essential modern JS features you should know',
 2, 1, 'published', 389, NOW() - INTERVAL 7 DAY),
('Hidden Gems of Tokyo', 'hidden-gems-of-tokyo',
 'Beyond the tourist trail, Tokyo offers...',
 'Discover Tokyo like a local',
 3, 2, 'draft', 0, NULL),
('Weekend Breakfast Ideas', 'weekend-breakfast-ideas',
 'Start your weekend with these...',
 'Simple and delicious breakfast recipes',
 5, 3, 'published', 267, NOW() - INTERVAL 5 DAY),
('Minimalist Living Guide', 'minimalist-living-guide',
 'Less stuff, more life...',
 'How to embrace minimalism',
 6, 4, 'draft', 0, NULL),
('Remote Work Best Practices', 'remote-work-best-practices',
 'Remote work is here to stay...',
 'Thrive as a remote worker',
 7, 5, 'published', 198, NOW() - INTERVAL 2 DAY);

INSERT INTO post_tags (post_id, tag_id) VALUES
(1, 1), (1, 3),
(2, 4), (2, 5),
(3, 5), (3, 8),
(4, 8), (4, 6),
(5, 5), (5, 6),
(6, 2), (6, 3),
(7, 4), (7, 5),
(8, 5), (8, 8),
(9, 6), (9, 8),
(10, 6), (10, 8);

INSERT INTO comments (post_id, user_id, parent_id, content) VALUES
(1, 4, NULL, 'Great introduction to Python! Very helpful for beginners.'),
(1, 5, NULL, 'I have been looking for a tutorial like this. Thanks!'),
(1, 6, 1, 'I agree, this is the best Python tutorial I have found.'),
(2, 4, NULL, 'I visited 3 of these places last year. Highly recommend!'),
(2, 5, NULL, 'Adding these to my bucket list!'),
(3, 5, NULL, 'Tried this recipe yesterday. The pizza was delicious!'),
(3, 6, NULL, 'What type of flour do you recommend?'),
(3, 7, 6, 'I use bread flour for a chewier crust.'),
(4, 6, NULL, 'These tips really helped me stay focused. Thank you!'),
(4, 8, NULL, 'Time blocking has changed my life!'),
(5, 4, NULL, 'Very insightful article about entrepreneurship.'),
(7, 5, NULL, 'Tokyo is amazing! Thanks for these hidden spots.'),
(7, 4, 12, 'Have you been to the Nezu Museum? It is beautiful.'),
(8, 6, NULL, 'Love these breakfast ideas. Quick and healthy!'),
(10, 4, NULL, 'Remote work definitely requires discipline.'),
(10, 5, NULL, 'I struggle with work-life balance when working from home.'),
(10, 8, 15, 'Setting boundaries is key. I have a dedicated workspace now.');

INSERT INTO user_sessions (user_id, login_time, logout_time, ip_address) VALUES
(1, NOW() - INTERVAL 1 HOUR, NOW() - INTERVAL 30 MINUTE, '192.168.1.1'),
(2, NOW() - INTERVAL 2 HOUR, NOW() - INTERVAL 1 HOUR, '192.168.1.2'),
(3, NOW() - INTERVAL 3 HOUR, NOW() - INTERVAL 2 HOUR, '192.168.1.3'),
(4, NOW() - INTERVAL 4 HOUR, NOW() - INTERVAL 3 HOUR, '192.168.1.4'),
(5, NOW() - INTERVAL 5 HOUR, NULL, '192.168.1.5'),
(6, NOW() - INTERVAL 30 MINUTE, NULL, '192.168.1.6'),
(2, NOW() - INTERVAL 1 DAY, NOW() - INTERVAL 23 HOUR, '192.168.1.2'),
(3, NOW() - INTERVAL 2 DAY, NOW() - INTERVAL 23 HOUR, '192.168.1.3'),
(4, NOW() - INTERVAL 3 DAY, NOW() - INTERVAL 46 HOUR, '192.168.1.4');

-- ============================================================================
-- DATABASE STATISTICS
-- ============================================================================
-- Users: 8 | Categories: 5 | Tags: 8 | Posts: 10 | Post-Tags: 20
-- Comments: 17 | Sessions: 9
